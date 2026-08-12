import base64
import binascii
import hashlib
import json
import os
import re
import secrets
import shutil
import threading
import tempfile
import time
import unicodedata
from copy import deepcopy
from pathlib import Path
from typing import Dict, List, Optional

from app.core.errors import AdapterError
from app.core.features import full_document_review_enabled
from app.core.runtime_paths import resolve_runtime_paths
from app.services.long_task_coordinator import (
    LongTaskCancelled,
    LongTaskContinuation,
    LongTaskCoordinator,
    get_long_task_coordinator,
)
from app.services.model_configurations import ACCESS_DIRECT_MODEL
from app.services.provider_client import ProviderClient


TASK_TYPE = "word.document_review.full"
LEGACY_CHUNK_SCHEMA_VERSION = "word.document_review.full.chunk.v1"
CHUNK_SCHEMA_VERSION = "word.document_review.full.chunk.v2"
REPORT_SCHEMA_VERSION = "word.document_review.full.report.v1"
REPORT_RESULT_TTL_SECONDS = 24 * 60 * 60
RECOVERABLE_FAILURE_TTL_SECONDS = 2 * 60 * 60
PERSISTENCE_SCHEMA_VERSION = 1
DEFAULT_ISSUE_PAGE_SIZE = 20
MAX_ISSUE_PAGE_SIZE = 100
MAX_REVIEW_CHARACTERS = 120000
SINGLE_CHUNK_MAX_REVIEW_CHARACTERS = 20000
STANDARD_REVIEW_CHARACTERS = 60000
REVIEW_CHUNK_TARGET_CHARACTERS = 18000
REVIEW_CHUNK_HARD_LIMIT = 20000
REVIEW_CHUNK_OVERLAP_CHARACTERS = 800
CHUNK_STRATEGY_VERSION = "word.full.chunking.v2"
SATURATION_SPLIT_LIMITS = (9000, 4500)
MAX_CHUNK_ISSUES = 200
MAX_CHUNK_FACTS = 80
MAX_CHUNK_CROSS_CHECKS = 40
MAX_AGGREGATE_INPUT_CHARACTERS = 60000
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
_LOCATIONS = {"body", "chapter", "table"}
_ENUMERATION_STATUSES = {"complete", "limited"}
_ISSUE_STATUSES = {"open", "processed", "ignored"}
_ANCHOR_VERIFICATIONS = {"verified", "unverified"}
_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
_NON_RETRYABLE_PROVIDER_CODES = {
    "PROVIDER_TIMEOUT",
    "DIFY_TIMEOUT",
    "MODEL_CONFIG_INCOMPLETE",
    "MODEL_DIRECT_REQUIRED",
    "MODEL_INPUT_BUDGET_EXCEEDED",
    "MODEL_PARAMETER_INVALID",
    "PROVIDER_AUTH_FAILED",
    "PROVIDER_PERMISSION_DENIED",
}
_RETRYABLE_PROVIDER_CODES = {
    "PROVIDER_UNREACHABLE",
    "PROVIDER_MID_STREAM_DISCONNECT",
    "DIFY_UNREACHABLE",
    "ADAPTER_UNAVAILABLE",
}
_NON_RECOVERABLE_FAILURE_CODES = {
    "FULL_DOCUMENT_REVIEW_AUTH_SNAPSHOT_MISMATCH",
    "FULL_DOCUMENT_REVIEW_CALL_LIMIT_EXCEEDED",
    "FULL_DOCUMENT_REVIEW_SNAPSHOT_MISMATCH",
    "FULL_DOCUMENT_REVIEW_TOO_LARGE",
    "FULL_DOCUMENT_REVIEW_AGGREGATE_INPUT_TOO_LARGE",
    "MODEL_CONFIG_INCOMPLETE",
    "MODEL_DIRECT_REQUIRED",
    "MODEL_CONTEXT_TOKENS_REQUIRED",
    "MODEL_OUTPUT_TOKENS_REQUIRED",
    "MODEL_OUTPUT_TOKENS_TOO_SMALL",
    "MODEL_INPUT_OVER_BUDGET",
    "MODEL_INPUT_BUDGET_EXCEEDED",
    "MODEL_PARAMETER_INVALID",
    "PROVIDER_AUTH_FAILED",
    "PROVIDER_PERMISSION_DENIED",
    "SYSTEM_PROMPT_DAMAGED",
    "SYSTEM_PROMPT_MISSING",
    "SYSTEM_PROMPT_MANIFEST_INVALID",
}
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
_EXPORT_BLOCKED_KEYS = {
    "blocks",
    "sourceText",
    "fullSnapshot",
    "rawAnswer",
    "rawResponse",
    "modelResponse",
    "apiKey",
    "apiKeyRef",
    "keyFingerprint",
    "localPath",
    "tempPath",
    "stagingPath",
    "errorDetail",
}
_EXPORT_BLOCKED_KEY_NAMES = {
    re.sub(r"[^a-z0-9]", "", key.casefold())
    for key in _EXPORT_BLOCKED_KEYS
} | {
    "fulltext",
    "documenttext",
    "snapshottext",
    "modelrawresponse",
}


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


def _derived_id(*parts: object) -> str:
    raw = "-".join(str(part) for part in parts if str(part))
    if len(raw) <= 96:
        return raw
    return "{0}-{1}".format(raw[:47], _sha256_text(raw)[:48])


def _report_sha256(report: Dict) -> str:
    payload = {
        key: value for key, value in report.items() if key != "reportSha256"
    }
    return _sha256_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )


def _review_character_count(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def _normalize_issue_semantic(value: object) -> str:
    """Normalize model wording before using it in a stable issue identity."""
    return re.sub(
        r"\s+", " ", unicodedata.normalize("NFKC", str(value or ""))
    ).strip().casefold()


def _sanitize_export_value(value: object) -> object:
    """Remove private execution data from user-controlled report exports."""
    if isinstance(value, dict):
        return {
            key: _sanitize_export_value(item)
            for key, item in value.items()
            if not str(key).startswith("_")
            and re.sub(r"[^a-z0-9]", "", str(key).casefold())
            not in _EXPORT_BLOCKED_KEY_NAMES
        }
    if isinstance(value, list):
        return [_sanitize_export_value(item) for item in value]
    return value


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
        self._job_records: Dict[str, Dict] = {}
        self._recovery_rejections: Dict[str, Dict] = {}
        self._lock = threading.Lock()
        self._cleanup_stop = threading.Event()
        self._cleanup_thread = None
        self._staging_ttl_seconds = max(int(staging_ttl_seconds), 1)
        self._last_cleanup_at = 0.0
        self._cleanup_expired(force=True)
        self._restore_persisted_jobs()

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

    def _job_path(self, job_id: str) -> Path:
        if not _SAFE_ID.fullmatch(str(job_id or "")):
            return self.staging_root / "job-invalid" / "job.json"
        return self.staging_root / "job-{0}".format(job_id) / "job.json"

    def _job_dir(self, job_id: str) -> Path:
        return self._job_path(job_id).parent

    @staticmethod
    def _canonical_sha256(value: object) -> str:
        return _sha256_text(
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )

    def _prompt_identity(self) -> Dict:
        stages = (
            "word.document_review.full.chunk",
            "word.document_review.full.chunk.correction",
            "word.document_review.full.aggregate",
            "word.document_review.full.aggregate.correction",
        )
        store = getattr(self.provider_client, "system_prompt_store", None)
        metadata = []
        for stage in stages:
            item = {"stage": stage, "version": "unavailable", "sha256": ""}
            if store is not None:
                try:
                    loaded = store.metadata(stage)
                    item = {
                        "stage": stage,
                        "version": str(loaded.get("version", "")),
                        "sha256": str(loaded.get("sha256", "")),
                    }
                except Exception:
                    pass
            metadata.append(item)
        return {
            "version": "word-full-review-prompts.v1",
            "stages": metadata,
            "sha256": self._canonical_sha256(metadata),
        }

    @classmethod
    def _auth_identity(cls, task_auth: Dict) -> Dict:
        api_key = str(task_auth.get("apiKey", ""))
        model_configuration = task_auth.get("modelConfiguration")
        config = {
            key: task_auth.get(key)
            for key in (
                "providerBaseUrl",
                "providerChatPath",
                "providerMode",
                "providerType",
                "accessMethod",
                "modelConfigurationId",
                "modelConfigurationName",
                "modelName",
                "temperature",
                "maxOutputTokens",
                "contextWindowTokens",
                "contextWindowTokensExplicit",
                "apiKeyRef",
                "providerInputMode",
            )
        }
        if isinstance(model_configuration, dict):
            config["modelConfigurationVersion"] = model_configuration.get("configVersion")
        return {
            "configuration": config,
            "configurationSha256": cls._canonical_sha256(config),
            "apiKeyRef": str(task_auth.get("apiKeyRef", "")),
            "keyFingerprint": _sha256_text(api_key) if api_key else "",
        }

    def _build_task_identity(self, snapshot: Dict) -> Dict:
        auth_identity = snapshot.get("authIdentity") or self._auth_identity(
            snapshot.get("taskAuth", {})
        )
        identity = {
            "snapshotSha256": str(snapshot.get("contentSha256", "")),
            "documentIdSha256": str(snapshot.get("documentIdSha256", "")),
            "documentType": str(snapshot.get("documentType", "")),
            "reviewPrompt": str(snapshot.get("reviewPrompt", "")),
            "writingPolicyScene": str(snapshot.get("writingPolicyScene", "auto")),
            "coverage": deepcopy(snapshot.get("coverage", {})),
            "auth": auth_identity,
            "prompt": snapshot.get("promptIdentity") or self._prompt_identity(),
            "chunkStrategyVersion": CHUNK_STRATEGY_VERSION,
        }
        return {
            "version": "word-full-review-task-identity.v1",
            "fields": identity,
            "sha256": self._canonical_sha256(identity),
        }

    @staticmethod
    def _persistent_snapshot(snapshot: Dict) -> Dict:
        safe = deepcopy(snapshot)
        safe.pop("taskAuth", None)
        safe.pop("_reviewState", None)
        safe["authIdentity"] = deepcopy(
            snapshot.get("authIdentity") or FullDocumentReviewService._auth_identity({})
        )
        return safe

    @staticmethod
    def _persistent_state(state: Dict) -> Dict:
        safe = deepcopy(state)
        for key in ("rawAnswer", "answer", "modelResponse", "providerResponse"):
            safe.pop(key, None)
        return safe

    def _persist_job_state(
        self,
        snapshot: Dict,
        state: Dict,
        status: str = "active",
        error_code: str = "",
    ) -> None:
        if not snapshot.get("_persistentJob"):
            return
        job_id = str(snapshot.get("jobId", ""))
        if not _SAFE_ID.fullmatch(job_id):
            return
        if not snapshot.get("authIdentity"):
            snapshot["authIdentity"] = self._auth_identity(snapshot.get("taskAuth", {}))
        if not snapshot.get("taskIdentity"):
            snapshot["taskIdentity"] = self._build_task_identity(snapshot)
        now = self._wall_clock()
        with self._lock:
            previous = self._job_records.get(job_id, {})
            checkpoint_sequence = int(previous.get("checkpointSequence", 0) or 0) + 1
        persisted_snapshot = self._persistent_snapshot(snapshot)
        persisted_state = self._persistent_state(state)
        checkpoint = {
            "schemaVersion": PERSISTENCE_SCHEMA_VERSION,
            "jobId": job_id,
            "checkpointSequence": checkpoint_sequence,
            "completedChunkIds": [
                str(item.get("chunkId", ""))
                for item in persisted_state.get("parsedChunks", [])
                if isinstance(item, dict)
            ],
            "state": persisted_state,
        }
        checkpoint["checkpointSha256"] = self._canonical_sha256(
            {key: value for key, value in checkpoint.items() if key != "checkpointSha256"}
        )
        record = {
            "schemaVersion": PERSISTENCE_SCHEMA_VERSION,
            "jobId": job_id,
            "traceId": str(snapshot.get("traceId", "")),
            "taskType": TASK_TYPE,
            "status": status,
            "createdAt": previous.get("createdAt", now),
            "updatedAt": now,
            "expiresAt": (
                now + RECOVERABLE_FAILURE_TTL_SECONDS
                if status == "recoverable_failed"
                else 0
            ),
            "errorCode": str(error_code or ""),
            "checkpointSequence": checkpoint_sequence,
            "taskIdentity": deepcopy(snapshot.get("taskIdentity") or self._build_task_identity(snapshot)),
            "snapshot": persisted_snapshot,
            "checkpoint": checkpoint,
        }
        record["recordSha256"] = self._canonical_sha256(
            {key: value for key, value in record.items() if key != "recordSha256"}
        )
        self._ensure_root()
        job_dir = self._job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(str(job_dir), 0o700)
        self._write_private_json(job_dir / "job.json", record)
        self._write_private_json(job_dir / "checkpoint.json", checkpoint)
        with self._lock:
            self._job_records[job_id] = record

    def _load_persisted_job(self, path: Path) -> Optional[Dict]:
        try:
            with path.open("r", encoding="utf-8") as handle:
                record = json.load(handle)
        except (OSError, ValueError):
            return None
        if not isinstance(record, dict) or record.get("schemaVersion") != PERSISTENCE_SCHEMA_VERSION:
            return None
        expected = self._canonical_sha256(
            {key: value for key, value in record.items() if key != "recordSha256"}
        )
        if record.get("recordSha256") != expected:
            return None
        checkpoint = record.get("checkpoint")
        if not isinstance(checkpoint, dict):
            return None
        try:
            with path.with_name("checkpoint.json").open("r", encoding="utf-8") as handle:
                external_checkpoint = json.load(handle)
        except (OSError, ValueError):
            return None
        if external_checkpoint != checkpoint:
            return None
        checkpoint_expected = self._canonical_sha256(
            {key: value for key, value in checkpoint.items() if key != "checkpointSha256"}
        )
        if checkpoint.get("checkpointSha256") != checkpoint_expected:
            return None
        snapshot = record.get("snapshot")
        state = checkpoint.get("state")
        if not isinstance(snapshot, dict) or not isinstance(state, dict):
            return None
        if self._contains_secret_field(record):
            return None
        if (
            checkpoint.get("jobId") != record.get("jobId")
            or checkpoint.get("checkpointSequence") != record.get("checkpointSequence")
        ):
            return None
        blocks = snapshot.get("blocks")
        if not isinstance(blocks, list) or not blocks:
            return None
        try:
            source_text = "\n".join(self._block_texts(blocks))
            snapshot_valid = (
                _sha256_text(source_text) == snapshot.get("contentSha256")
                and _review_character_count(source_text) == snapshot.get("reviewCharacterCount")
                and (
                    not snapshot.get("structureSha256")
                    or self._structure_sha256(blocks) == snapshot.get("structureSha256")
                )
            )
        except (KeyError, TypeError, ValueError):
            return None
        if not snapshot_valid:
            return None
        completed_chunk_ids = checkpoint.get("completedChunkIds")
        parsed_chunk_ids = [
            item.get("chunkId")
            for item in state.get("parsedChunks", [])
            if isinstance(item, dict)
        ]
        if completed_chunk_ids != parsed_chunk_ids:
            return None
        if record.get("taskIdentity") != self._build_task_identity(snapshot):
            return None
        snapshot["_reviewState"] = state
        snapshot["_persistentJob"] = True
        return record

    @classmethod
    def _contains_secret_field(cls, value: object) -> bool:
        if isinstance(value, dict):
            return any(
                key == "apiKey" or cls._contains_secret_field(item)
                for key, item in value.items()
            )
        if isinstance(value, list):
            return any(cls._contains_secret_field(item) for item in value)
        return False

    def _restore_persisted_jobs(self) -> None:
        if not full_document_review_enabled():
            return
        root = self.staging_root
        if not root.exists() or not root.is_dir():
            return
        try:
            paths = sorted(
                child / "job.json"
                for child in root.iterdir()
                if child.is_dir() and child.name.startswith("job-")
            )
        except OSError:
            return
        now = self._wall_clock()
        for path in paths:
            record = self._load_persisted_job(path)
            if record is None:
                self._remove_job_data(path.parent.name[4:])
                continue
            expiry = float(record.get("expiresAt", 0) or 0)
            if expiry and now >= expiry:
                self._remove_job_data(str(record.get("jobId", "")))
                continue
            snapshot = record.get("snapshot", {})
            job_id = str(record.get("jobId", ""))
            if not _SAFE_ID.fullmatch(job_id) or str(snapshot.get("jobId", "")) != job_id:
                self._remove_job_data(job_id)
                continue
            try:
                task_auth = self.provider_client.resolve_task_auth("word.document_review")
                self._require_full_review_ready(task_auth)
            except Exception:
                self._reject_recovery(job_id, record, "FULL_DOCUMENT_REVIEW_AUTH_SNAPSHOT_MISMATCH")
                continue
            current_identity = self._auth_identity(task_auth)
            expected_identity = snapshot.get("authIdentity")
            if expected_identity != current_identity:
                self._reject_recovery(job_id, record, "FULL_DOCUMENT_REVIEW_AUTH_SNAPSHOT_MISMATCH")
                continue
            if snapshot.get("promptIdentity") and snapshot.get("promptIdentity") != self._prompt_identity():
                self._reject_recovery(job_id, record, "FULL_DOCUMENT_REVIEW_PROMPT_SNAPSHOT_MISMATCH")
                continue
            snapshot["taskAuth"] = task_auth
            snapshot["authIdentity"] = current_identity
            snapshot["taskIdentity"] = record.get("taskIdentity") or self._build_task_identity(snapshot)
            self._job_records[job_id] = record
            try:
                self._submit_persisted_snapshot(snapshot, persist=False)
            except Exception:
                self._reject_recovery(job_id, record, "FULL_DOCUMENT_REVIEW_RECOVERY_FAILED")

    def _reject_recovery(self, job_id: str, record: Dict, code: str) -> None:
        self._remove_job_data(job_id)
        self._recovery_rejections[job_id] = {
            "jobId": job_id,
            "traceId": str(record.get("traceId", "")),
            "taskType": TASK_TYPE,
            "status": "failed",
            "phase": "failed",
            "createdAt": record.get("createdAt", self._wall_clock()),
            "updatedAt": self._wall_clock(),
            "error": {
                "code": code,
                "message": "全篇审查任务无法在当前认证边界下恢复。",
            },
        }

    def _submit_persisted_snapshot(self, snapshot: Dict, persist: bool = True) -> Dict:
        job_id = str(snapshot.get("jobId", ""))
        snapshot["_persistentJob"] = True
        existing = self.coordinator.get(job_id, task_type=TASK_TYPE)
        if existing is not None:
            if existing.get("snapshotId") != snapshot.get("snapshotId"):
                raise AdapterError(
                    "FULL_DOCUMENT_REVIEW_JOB_ID_CONFLICT",
                    "客户端任务编号已绑定到其他全篇审查快照。",
                    status_code=409,
                )
            return existing
        if persist:
            state = snapshot.get("_reviewState") or self._initial_review_state(snapshot)
            snapshot["_reviewState"] = state
            self._persist_job_state(snapshot, state)
        job = self.coordinator.submit(
            job_id=job_id,
            trace_id=str(snapshot.get("traceId", "")),
            task_type=TASK_TYPE,
            runner=self._run_job,
            snapshot=snapshot,
            failure_code="FULL_DOCUMENT_REVIEW_JOB_FAILED",
            failure_message="全篇审查任务失败，未生成报告。",
            safe_failure_codes={
                "FULL_DOCUMENT_REVIEW_RESULT_INVALID",
                "FULL_DOCUMENT_REVIEW_AGGREGATE_INVALID",
                "FULL_DOCUMENT_REVIEW_AGGREGATE_INPUT_TOO_LARGE",
                "FULL_DOCUMENT_REVIEW_CALL_LIMIT_EXCEEDED",
                "FULL_DOCUMENT_REVIEW_AUTH_SNAPSHOT_MISMATCH",
                "MODEL_CONFIG_INCOMPLETE",
                "MODEL_DIRECT_REQUIRED",
                "PROVIDER_TIMEOUT",
                "PROVIDER_UNREACHABLE",
            },
            public_metadata={
                "reviewMode": "full",
                "snapshotId": str(snapshot.get("snapshotId", "")),
                "chunkCount": snapshot.get("capacity", {}).get("initialChunkCount", 0),
                "capacity": deepcopy(snapshot.get("capacity", {})),
            },
            allow_running_cancel=True,
        )
        self._job_records[job_id] = {
            **self._job_records.get(job_id, {}),
            "taskIdentity": deepcopy(snapshot.get("taskIdentity") or self._build_task_identity(snapshot)),
            "authIdentity": deepcopy(snapshot.get("authIdentity") or self._auth_identity(snapshot.get("taskAuth", {}))),
            "status": job.get("status", "queued"),
            "updatedAt": self._wall_clock(),
        }
        return job

    def _initial_review_state(self, snapshot: Dict) -> Dict:
        return {
            "pendingChunks": self._build_review_chunks(snapshot),
            "parsedChunks": [],
            "limitedRanges": [],
            "callCount": 0,
            "aggregateScheduled": False,
            "aggregateRetried": False,
            "aggregateResult": None,
        }

    def _reuse_active_task(self, snapshot: Dict) -> Optional[Dict]:
        identity = snapshot.get("taskIdentity") or self._build_task_identity(snapshot)
        expected = str(identity.get("sha256", ""))
        for job_id, record in list(self._job_records.items()):
            if str(record.get("taskIdentity", {}).get("sha256", "")) != expected:
                continue
            job = self.coordinator.get(job_id, task_type=TASK_TYPE)
            if job and job.get("status") in {"queued", "running", "failed"}:
                return job
        return None

    def _require_current_auth(self, snapshot: Dict) -> None:
        expected = snapshot.get("authIdentity")
        if not isinstance(expected, dict):
            return
        current = self.provider_client.resolve_task_auth("word.document_review")
        self._require_full_review_ready(current)
        if current is None or self._auth_identity(current) != expected:
            raise AdapterError(
                "FULL_DOCUMENT_REVIEW_AUTH_SNAPSHOT_MISMATCH",
                "全篇审查任务的模型配置或认证指纹已变化，拒绝继续使用当前任务。",
                status_code=409,
            )

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
                    "tablePath": self._normalize_table_path(item.get("tablePath", [])),
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
        anchor_ids = set()

        def reserve_anchor(anchor_id: str) -> None:
            if anchor_id in anchor_ids:
                raise AdapterError(
                    "FULL_DOCUMENT_REVIEW_BLOCK_INVALID",
                    "正文块和表格单元格标识必须全局唯一。",
                )
            anchor_ids.add(anchor_id)

        def reserve_table_cells(table: Dict) -> None:
            for row in table.get("rows", []):
                for cell in row.get("cells", []):
                    reserve_anchor(cell["cellId"])
            for nested in table.get("nestedTables", []):
                reserve_table_cells(nested)

        for block in normalized:
            reserve_anchor(block["blockId"])
            if block["blockType"] == "table":
                reserve_table_cells(block)
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
                "tableIndex": table.get("tableIndex", 0),
                "tablePath": self._normalize_table_path(table.get("tablePath", [])),
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
    def _normalize_table_path(value: object) -> List[Dict]:
        if value is None:
            return []
        if not isinstance(value, list) or len(value) > 32:
            raise AdapterError(
                "FULL_DOCUMENT_REVIEW_TABLE_INVALID", "表格路径格式无效。"
            )
        normalized = []
        for item in value:
            if not isinstance(item, dict) or set(item) != {"tableIndex", "rowIndex", "columnIndex"}:
                raise AdapterError(
                    "FULL_DOCUMENT_REVIEW_TABLE_INVALID", "表格路径格式无效。"
                )
            if any(type(item[key]) is not int or item[key] < 0 for key in item):
                raise AdapterError(
                    "FULL_DOCUMENT_REVIEW_TABLE_INVALID", "表格路径索引格式无效。"
                )
            if item["tableIndex"] <= 0:
                raise AdapterError(
                    "FULL_DOCUMENT_REVIEW_TABLE_INVALID", "表格路径索引格式无效。"
                )
            normalized.append({key: item[key] for key in ("tableIndex", "rowIndex", "columnIndex")})
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
        with self._lock:
            session = self._sessions.get(snapshot_id)
            if session is None:
                raise AdapterError(
                    "FULL_DOCUMENT_REVIEW_SNAPSHOT_NOT_FOUND",
                    "全篇审查快照不存在或已过期。",
                    status_code=404,
                )
            self._verify_snapshot_token(session, {"snapshotToken": snapshot_token})
            if session.get("status") == "submitted":
                existing_job_id = str(session.get("submittedJobId", ""))
                existing = self.coordinator.get(existing_job_id, task_type=TASK_TYPE)
                if existing is not None:
                    return existing
            if session.get("status") not in {"committed", "awaiting_confirmation"}:
                raise AdapterError(
                    "FULL_DOCUMENT_REVIEW_SNAPSHOT_STATE_INVALID",
                    "全篇审查快照状态不允许当前操作。",
                    status_code=409,
                )
            if session.get("status") == "awaiting_confirmation":
                if payload.get("confirmLarge") is not True:
                    raise AdapterError(
                        "FULL_DOCUMENT_REVIEW_CONFIRMATION_REQUIRED",
                        "大型全篇审查需要用户确认字符数、初始分片和调用上限。",
                        status_code=409,
                    )
                self._verify_confirmation_token(session, payload)
                session["confirmationTokenSha256"] = ""
            job_id = (
                requested_job_id
                if _SAFE_ID.fullmatch(requested_job_id)
                else "full-review-job-{0}".format(secrets.token_hex(16))
            )
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
                "writingPolicyScene": session.get("writingPolicyScene", "auto"),
                "documentIdSha256": session.get("documentIdSha256", ""),
                "coverage": deepcopy(session["coverage"]),
                "reviewCharacterCount": session["reviewCharacterCount"],
                "contentSha256": session["contentSha256"],
                "capacity": deepcopy(session["capacity"]),
                "tableCount": session.get("tableCount", 0),
                "cellCount": session.get("cellCount", 0),
                "committedAt": session["committedAt"],
                "taskAuth": task_auth,
            }
            snapshot["authIdentity"] = self._auth_identity(task_auth)
            snapshot["promptIdentity"] = self._prompt_identity()
            snapshot["taskIdentity"] = self._build_task_identity(snapshot)
            session["authIdentity"] = deepcopy(snapshot["authIdentity"])
            session["taskIdentity"] = deepcopy(snapshot["taskIdentity"])
            existing = self._reuse_active_task(snapshot)
            if existing is not None:
                session["status"] = "submitted"
                session["submittedJobId"] = existing["jobId"]
                reused_job = existing
            else:
                reused_job = None
                snapshot["_reviewState"] = self._initial_review_state(snapshot)
        if reused_job is not None:
            self._remove_snapshot(snapshot_id)
            return reused_job
        try:
            job = self._submit_persisted_snapshot(snapshot)
            if job.get("snapshotId") != snapshot_id:
                raise AdapterError(
                    "FULL_DOCUMENT_REVIEW_JOB_ID_CONFLICT",
                    "客户端任务编号已绑定到其他全篇审查快照。",
                    status_code=409,
                )
        except Exception:
            remove_job_data = False
            with self._lock:
                if session.get("status") == "submitting":
                    session["status"] = (
                        "awaiting_confirmation"
                        if session.get("capacity", {}).get("requiresConfirmation")
                        else "committed"
                    )
                    session.pop("submittedJobId", None)
                persisted = self._job_records.get(job_id, {})
                persisted_snapshot = persisted.get("snapshot", {})
                remove_job_data = not persisted or persisted_snapshot.get("snapshotId") == snapshot_id
            if remove_job_data:
                self._remove_job_data(job_id)
            raise
        with self._lock:
            session["status"] = "submitted"
        return job

    def get_job(self, job_id: str) -> Optional[Dict]:
        self._require_enabled()
        rejected = self._recovery_rejections.get(job_id)
        if rejected is not None:
            return deepcopy(rejected)
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
            job["enumerationLimitedRanges"] = deepcopy(
                result.get("enumerationLimitedRanges", [])
            )
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
            self._remove_job_data(job_id)
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
        if location and location not in _LOCATIONS:
            raise AdapterError(
                "FULL_DOCUMENT_REVIEW_ISSUE_FILTER_INVALID",
                "问题位置筛选值无效。",
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
        filtered_group_ids = {
            item.get("duplicateGroupId", "") for item in issues if item.get("duplicateGroupId")
        }
        duplicate_groups = {}
        for item in report.get("issues", []):
            group_id = item.get("duplicateGroupId", "")
            if group_id in filtered_group_ids:
                duplicate_groups.setdefault(group_id, []).append(item.get("issueId", ""))
        duplicate_groups = {
            group_id: issue_ids
            for group_id, issue_ids in duplicate_groups.items()
            if len(issue_ids) > 1
        }
        return {
            "items": selected,
            "total": len(issues),
            "pageSize": size,
            "page": (offset // size) + 1,
            "nextCursor": next_cursor,
            "hasMore": bool(next_cursor),
            "duplicateGroups": [
                {
                    "duplicateGroupId": group_id,
                    "issueIds": issue_ids,
                    "count": len(issue_ids),
                }
                for group_id, issue_ids in sorted(duplicate_groups.items())
            ],
            "filters": {
                "severity": severity,
                "category": category,
                "location": location,
                "status": status,
            },
            "sort": sort,
        }

    def update_issue_status(
        self,
        job_id: str,
        issue_id: str,
        status: Optional[str] = None,
        anchor_verification: Optional[str] = None,
    ) -> Dict:
        if not _SAFE_ID.fullmatch(str(issue_id or "")):
            raise AdapterError(
                "FULL_DOCUMENT_REVIEW_ISSUE_NOT_FOUND",
                "全篇审查问题不存在或已过期。",
                status_code=404,
            )
        if status is None and anchor_verification is None:
            raise AdapterError(
                "FULL_DOCUMENT_REVIEW_ISSUE_REQUEST_INVALID",
                "问题更新请求不能为空。",
            )
        if status is not None and status not in _ISSUE_STATUSES:
            raise AdapterError(
                "FULL_DOCUMENT_REVIEW_ISSUE_STATUS_INVALID",
                "问题处理状态无效。",
            )
        if anchor_verification is not None and anchor_verification not in _ANCHOR_VERIFICATIONS:
            raise AdapterError(
                "FULL_DOCUMENT_REVIEW_ANCHOR_VERIFICATION_INVALID",
                "问题锚点验证状态无效。",
            )
        report = self._require_report(job_id)
        for issue in report.get("issues", []):
            if issue.get("issueId") == issue_id:
                if status is not None:
                    issue["status"] = status
                if anchor_verification is not None:
                    issue["anchorVerification"] = anchor_verification
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
        self._remove_job_data(job_id)
        return {"jobId": job_id, "status": "deleted"}

    def _run_job(self, snapshot: Dict, progress) -> object:
        job_id = str(snapshot.get("jobId", ""))
        state = snapshot.setdefault("_reviewState", self._initial_review_state(snapshot))
        state.setdefault("pendingChunks", self._build_review_chunks(snapshot))
        state.setdefault("parsedChunks", [])
        state.setdefault("limitedRanges", [])
        state.setdefault("callCount", 0)
        state.setdefault("aggregateScheduled", False)
        state.setdefault("aggregateRetried", False)
        state.setdefault("aggregateResult", None)
        call_limit = int(snapshot.get("capacity", {}).get("callLimit", 0) or 0)
        keep_staging = False
        active_chunk = None

        def call_provider(chunk: Dict, correction: bool = False) -> str:
            if state["callCount"] >= call_limit:
                raise AdapterError(
                    "FULL_DOCUMENT_REVIEW_CALL_LIMIT_EXCEEDED",
                    "全篇审查已达到当前容量档位的模型调用上限，未继续发起模型请求。",
                    status_code=409,
                )
            state["callCount"] += 1
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

        def call_aggregate(payload: Dict, correction: bool = False) -> object:
            if state["callCount"] >= call_limit:
                raise AdapterError(
                    "FULL_DOCUMENT_REVIEW_CALL_LIMIT_EXCEEDED",
                    "全篇审查已达到当前容量档位的模型调用上限，未继续发起模型请求。",
                    status_code=409,
                )
            state["callCount"] += 1
            return self.provider_client.full_document_review_aggregate(
                payload,
                snapshot.get("traceId", ""),
                snapshot["taskAuth"],
                correction=correction,
            )

        try:
            self._require_current_auth(snapshot)
            self._raise_if_cancelled(job_id)
            if not state["pendingChunks"]:
                if len(state["parsedChunks"]) > 1 and state.get("aggregateResult") is None:
                    if not state.get("aggregateScheduled"):
                        state["aggregateScheduled"] = True
                        progress("aggregating")
                        keep_staging = True
                        self._persist_job_state(snapshot, state)
                        return LongTaskContinuation(snapshot, phase="aggregating")
                    aggregate_input = self._build_aggregate_input(snapshot, state["parsedChunks"])
                    progress("aggregating")
                    try:
                        aggregate_answer = call_aggregate(aggregate_input)
                    except AdapterError as exc:
                        if self._is_retryable_provider_error(exc) and not state.get("aggregateRetried"):
                            state["aggregateRetried"] = True
                            progress("retrying")
                            keep_staging = True
                            self._persist_job_state(snapshot, state, status="recoverable_failed", error_code=exc.code)
                            return LongTaskContinuation(snapshot, phase="aggregating")
                        raise
                    try:
                        aggregate_result = self._parse_aggregate_result(
                            aggregate_answer, aggregate_input
                        )
                    except AdapterError as exc:
                        if exc.code != "FULL_DOCUMENT_REVIEW_AGGREGATE_INVALID" or state.get("aggregateRetried"):
                            raise
                        state["aggregateRetried"] = True
                        progress("retrying")
                        aggregate_answer = call_aggregate(aggregate_input, correction=True)
                        aggregate_result = self._parse_aggregate_result(
                            aggregate_answer, aggregate_input
                        )
                    state["aggregateResult"] = aggregate_result
                    self._persist_job_state(snapshot, state)
                progress("aggregating")
                report = self._build_report(
                    snapshot,
                    state["parsedChunks"],
                    state.get("limitedRanges", []),
                    state.get("aggregateResult"),
                )
                self._save_report(job_id, report)
                return report

            chunk = state["pendingChunks"].pop(0)
            active_chunk = chunk
            self._raise_if_cancelled(job_id)
            progress("chunking")
            try:
                progress("provider_processing")
                answer = call_provider(chunk)
            except AdapterError as exc:
                if self._is_retryable_provider_error(exc) and not chunk.get("_retried"):
                    self._raise_if_cancelled(job_id)
                    chunk["_retried"] = True
                    state["pendingChunks"].insert(0, chunk)
                    progress("retrying")
                    keep_staging = True
                    self._persist_job_state(snapshot, state)
                    return LongTaskContinuation(snapshot)
                raise

            self._raise_if_cancelled(job_id)
            progress("parsing")
            try:
                parsed = self._parse_strict_result(answer, snapshot, chunk)
            except AdapterError as exc:
                if exc.code == "FULL_DOCUMENT_REVIEW_OUTPUT_SATURATED":
                    split_chunks = self._split_saturated_chunk(chunk)
                    if not split_chunks:
                        raise
                    progress("splitting")
                    state["pendingChunks"] = split_chunks + state["pendingChunks"]
                    keep_staging = True
                    self._persist_job_state(snapshot, state)
                    return LongTaskContinuation(snapshot)
                if exc.code != "FULL_DOCUMENT_REVIEW_RESULT_INVALID" or chunk.get("_retried"):
                    raise
                self._raise_if_cancelled(job_id)
                chunk["_retried"] = True
                progress("retrying")
                corrected = call_provider(chunk, correction=True)
                self._raise_if_cancelled(job_id)
                parsed = self._parse_strict_result(corrected, snapshot, chunk)

            if parsed.get("_saturationReason"):
                split_chunks = self._split_saturated_chunk(chunk)
                if split_chunks:
                    progress("splitting")
                    state["pendingChunks"] = split_chunks + state["pendingChunks"]
                    keep_staging = True
                    self._persist_job_state(snapshot, state)
                    return LongTaskContinuation(snapshot)
                state["limitedRanges"].append(chunk["chunkId"])

            parsed.pop("_saturationReason", None)
            state["parsedChunks"].append(parsed)
            self._persist_job_state(snapshot, state)
            self._raise_if_cancelled(job_id)
            if state["pendingChunks"]:
                keep_staging = True
                self._persist_job_state(snapshot, state)
                return LongTaskContinuation(snapshot)
            if len(state["parsedChunks"]) > 1 and state.get("aggregateResult") is None:
                keep_staging = True
                self._persist_job_state(snapshot, state)
                return LongTaskContinuation(snapshot, phase="aggregating")
            progress("aggregating")
            report = self._build_report(
                snapshot,
                state["parsedChunks"],
                state.get("limitedRanges", []),
                state.get("aggregateResult"),
            )
            self._save_report(job_id, report)
            return report
        except AdapterError as exc:
            if snapshot.get("_persistentJob") and self._is_recoverable_failure(exc):
                keep_staging = True
                if active_chunk is not None and not any(
                    item.get("chunkId") == active_chunk.get("chunkId")
                    for item in state.get("pendingChunks", [])
                ):
                    state["pendingChunks"].insert(0, active_chunk)
                self._persist_job_state(
                    snapshot,
                    state,
                    status="recoverable_failed",
                    error_code=exc.code,
                )
            raise
        finally:
            if not keep_staging:
                self._remove_snapshot(str(snapshot.get("snapshotId", "")))
                self._remove_job_data(job_id)

    @staticmethod
    def _is_recoverable_failure(error: AdapterError) -> bool:
        return str(getattr(error, "code", "")) not in _NON_RECOVERABLE_FAILURE_CODES

    @staticmethod
    def _is_retryable_provider_error(error: AdapterError) -> bool:
        code = str(getattr(error, "code", ""))
        if code in _NON_RETRYABLE_PROVIDER_CODES or "TIMEOUT" in code.upper():
            return False
        if code in _RETRYABLE_PROVIDER_CODES:
            return True
        return int(getattr(error, "status_code", 0) or 0) in {502, 503, 504}

    @classmethod
    def _split_saturated_chunk(cls, chunk: Dict) -> List[Dict]:
        split_level = int(chunk.get("_splitLevel", 0) or 0)
        if split_level >= len(SATURATION_SPLIT_LIMITS):
            return []
        limit = SATURATION_SPLIT_LIMITS[split_level]
        blocks = []
        for block in chunk.get("blocks", []):
            block_count = sum(
                _review_character_count(text) for text in cls._block_texts([block])
            )
            if block_count <= limit:
                blocks.append(deepcopy(block))
                continue
            if block.get("blockType") == "table":
                blocks.extend(cls._split_table_block(block, limit))
                continue
            for fragment in cls._split_text_unit(block, limit):
                if block.get("isOverlap") is True:
                    fragment["isOverlap"] = True
                    fragment["core"] = False
                    fragment["contextOnly"] = True
                blocks.append(fragment)
        if len(blocks) < 2:
            return []
        chunks = []
        current = []
        current_count = 0
        for block in blocks:
            block_count = sum(
                _review_character_count(text) for text in cls._block_texts([block])
            )
            if current and current_count + block_count > limit:
                chunks.append(current)
                current = []
                current_count = 0
            current.append(block)
            current_count += block_count
        if current:
            chunks.append(current)
        return [
            {
                "chunkId": _derived_id(chunk["chunkId"], "split", index),
                "blocks": deepcopy(blocks),
                "sourceText": "\n".join(cls._block_texts(blocks)),
                "_splitLevel": split_level + 1,
            }
            for index, blocks in enumerate(chunks, 1)
        ]

    @staticmethod
    def _split_text(text: str, limit: int) -> List[str]:
        fragments = []
        start = 0
        while start < len(text):
            end = min(start + limit, len(text))
            while end > start and _review_character_count(text[start:end]) > limit:
                end -= 1
            if end <= start:
                raise AdapterError(
                    "FULL_DOCUMENT_REVIEW_OUTPUT_SATURATED",
                    "审查分片无法按当前字符边界拆分。",
                    status_code=409,
                )
            fragments.append(text[start:end])
            start = end
        return fragments

    @staticmethod
    def _block_character_count(block: Dict) -> int:
        return sum(_review_character_count(text) for text in FullDocumentReviewService._block_texts([block]))

    @classmethod
    def _block_core_character_count(cls, block: Dict) -> int:
        if block.get("isOverlap") is True or block.get("contextOnly") is True:
            return 0
        if block.get("blockType") != "table":
            return cls._block_character_count(block)

        def table_count(table: Dict) -> int:
            if table.get("isOverlap") is True:
                return 0
            total = 0
            for row in table.get("rows", []):
                if row.get("isOverlap") is True:
                    continue
                for cell in row.get("cells", []):
                    if cell.get("isOverlap") is not True:
                        total += _review_character_count(cell.get("text", ""))
            total += sum(table_count(nested) for nested in table.get("nestedTables", []))
            return total

        return table_count(block)

    @staticmethod
    def _slice_by_review_chars(text: str, start: int, end: int) -> str:
        if start >= end:
            return ""
        current = 0
        first = None
        last = None
        for index, character in enumerate(text):
            next_count = current + _review_character_count(character)
            if first is None and next_count > start:
                first = index
            if next_count <= end:
                last = index + 1
            current = next_count
            if current >= end:
                break
        if first is None:
            return ""
        return text[first : last or first]

    @classmethod
    def _split_text_semantically(cls, text: str, limit: int) -> List[Dict]:
        total = _review_character_count(text)
        if total <= limit:
            return [{"text": text, "sourceOffsetStart": 0, "sourceOffsetEnd": total}]
        pieces = []
        start = 0
        while start < total:
            target_end = min(start + limit, total)
            candidate = target_end
            minimum = start + max(1, int(limit * 0.55))
            raw = cls._slice_by_review_chars(text, start, target_end)
            raw_length = _review_character_count(raw)
            if raw_length < target_end - start:
                target_end = start + raw_length
                candidate = target_end
            python_end = 0
            consumed = 0
            for index, character in enumerate(text):
                next_count = consumed + _review_character_count(character)
                if next_count > candidate:
                    break
                python_end = index + 1
                consumed = next_count
            boundary = None
            for index in range(python_end - 1, -1, -1):
                if text[index] in "。！？!?；;\n。":
                    boundary = index + 1
                    break
            if boundary is None:
                for index in range(python_end - 1, -1, -1):
                    if text[index].isspace():
                        boundary = index + 1
                        break
            if boundary is not None:
                boundary_count = _review_character_count(text[:boundary])
                if boundary_count >= minimum:
                    candidate = boundary_count
            if candidate <= start:
                candidate = min(start + limit, total)
            piece = cls._slice_by_review_chars(text, start, candidate)
            actual_end = start + _review_character_count(piece)
            if not piece or actual_end <= start:
                raise AdapterError(
                    "FULL_DOCUMENT_REVIEW_CHUNKING_FAILED",
                    "正文分片无法按审查字符边界拆分。",
                    status_code=409,
                )
            pieces.append({
                "text": piece,
                "sourceOffsetStart": start,
                "sourceOffsetEnd": actual_end,
            })
            start = actual_end
        return pieces

    @classmethod
    def _split_text_block(cls, block: Dict, limit: int) -> List[Dict]:
        fragments = cls._split_text_semantically(block.get("text", ""), limit)
        result = []
        for index, fragment in enumerate(fragments, 1):
            item = deepcopy(block)
            item["text"] = fragment["text"]
            item["sourceBlockId"] = block["blockId"]
            item["sourceOffsetStart"] = fragment["sourceOffsetStart"]
            item["sourceOffsetEnd"] = fragment["sourceOffsetEnd"]
            item["isOverlap"] = False
            item["core"] = True
            if len(fragments) > 1:
                item["blockId"] = _derived_id(block["blockId"], "part", index)
            result.append(item)
        return result

    @classmethod
    def _split_text_unit(cls, block: Dict, limit: int) -> List[Dict]:
        pieces = cls._split_text_semantically(block.get("text", ""), limit)
        result = []
        base_offset = int(block.get("sourceOffsetStart", 0) or 0)
        for index, piece in enumerate(pieces, 1):
            item = deepcopy(block)
            item["text"] = piece["text"]
            item["sourceOffsetStart"] = base_offset + piece["sourceOffsetStart"]
            item["sourceOffsetEnd"] = base_offset + piece["sourceOffsetEnd"]
            item["isOverlap"] = False
            item["core"] = True
            if len(pieces) > 1:
                item["blockId"] = _derived_id(block["blockId"], "part", index)
            result.append(item)
        return result

    @classmethod
    def _split_table_block(cls, block: Dict, limit: int) -> List[Dict]:
        rows = block.get("rows", [])
        if cls._block_character_count(block) <= limit:
            item = deepcopy(block)
            item["sourceBlockId"] = block["blockId"]
            item["isOverlap"] = False
            item["core"] = True
            return [item]

        header = deepcopy(rows[0]) if rows else None
        nested_by_id = {
            nested.get("tableId"): nested
            for nested in block.get("nestedTables", [])
            if nested.get("tableId")
        }
        fragments = []
        current_rows = []
        current_count = 0
        current_nested_tables = []

        def row_count(row: Dict) -> int:
            cell_count = sum(
                _review_character_count(cell.get("text", ""))
                for cell in row.get("cells", [])
            )
            nested_count = sum(
                _review_character_count("\n".join(cls._table_texts(nested_by_id[nested_id])))
                for cell in row.get("cells", [])
                for nested_id in cell.get("nestedTableIds", [])
                if nested_id in nested_by_id
            )
            return cell_count + nested_count

        def overlap_header() -> Optional[Dict]:
            if header is None:
                return None
            header_copy = deepcopy(header)
            header_copy["isOverlap"] = True
            for cell in header_copy.get("cells", []):
                cell["isOverlap"] = True
            return header_copy

        def flush() -> None:
            nonlocal current_rows, current_count, current_nested_tables
            if not current_rows:
                return
            fragment = deepcopy(block)
            fragment["rows"] = current_rows
            fragment["nestedTables"] = deepcopy(current_nested_tables)
            if fragments:
                def mark_nested(table: Dict) -> None:
                    table["isOverlap"] = True
                    for row in table.get("rows", []):
                        row["isOverlap"] = True
                        for cell in row.get("cells", []):
                            cell["isOverlap"] = True
                    for nested in table.get("nestedTables", []):
                        mark_nested(nested)
                for nested in fragment["nestedTables"]:
                    mark_nested(nested)
            fragment["sourceBlockId"] = block["blockId"]
            fragment["isOverlap"] = False
            fragment["core"] = True
            fragment["blockId"] = _derived_id(block["blockId"], "part", len(fragments) + 1)
            fragments.append(fragment)
            current_rows = []
            current_count = 0
            current_nested_tables = []

        for row in rows:
            count = row_count(row)
            if count > limit:
                if not (
                    header is not None
                    and len(current_rows) == 1
                    and current_rows[0].get("rowIndex") == header.get("rowIndex")
                ):
                    flush()
                else:
                    current_rows = []
                    current_count = 0
                    current_nested_tables = []
                for cell in row.get("cells", []):
                    nested_tables = [
                        deepcopy(nested_by_id[nested_id])
                        for nested_id in cell.get("nestedTableIds", [])
                        if nested_id in nested_by_id
                    ]
                    nested_count = sum(
                        _review_character_count("\n".join(cls._table_texts(nested)))
                        for nested in nested_tables
                    )
                    header_count = row_count(header) if header is not None else 0
                    cell_limit = max(1, limit - header_count - nested_count)
                    cell_fragments = cls._split_text_semantically(
                        cell.get("text", ""), cell_limit
                    )
                    for cell_fragment in cell_fragments:
                        cell_copy = deepcopy(cell)
                        cell_copy["text"] = cell_fragment["text"]
                        cell_copy["sourceCellId"] = cell["cellId"]
                        cell_copy["sourceOffsetStart"] = cell_fragment["sourceOffsetStart"]
                        cell_copy["sourceOffsetEnd"] = cell_fragment["sourceOffsetEnd"]
                        row_copy = {"rowIndex": row.get("rowIndex"), "cells": [cell_copy]}
                        header_copy = overlap_header()
                        current_rows = [header_copy] if header_copy is not None else []
                        current_count = row_count(header_copy) if header_copy is not None else 0
                        current_nested_tables = deepcopy(nested_tables)
                        current_count += nested_count
                        if current_count + _review_character_count(cell_copy["text"]) > limit:
                            flush()
                            current_rows = [header_copy] if header_copy is not None else []
                            current_count = row_count(header_copy) if header_copy is not None else 0
                            current_nested_tables = deepcopy(nested_tables)
                            current_count += nested_count
                        current_rows.append(row_copy)
                        current_count += _review_character_count(cell_copy["text"])
                        flush()
                continue
            proposed = current_count + count
            if current_rows and proposed > limit:
                flush()
                header_copy = overlap_header()
                if header_copy is not None:
                    current_rows = [header_copy]
                    current_count = row_count(header_copy)
            current_rows.append(deepcopy(row))
            current_count += count
            for nested_id in (
                nested_id
                for cell in row.get("cells", [])
                for nested_id in cell.get("nestedTableIds", [])
            ):
                if nested_id in nested_by_id and not any(
                    existing.get("tableId") == nested_id
                    for existing in current_nested_tables
                ):
                    current_nested_tables.append(deepcopy(nested_by_id[nested_id]))
        flush()
        if not fragments:
            return cls._split_text_block(
                {**block, "blockType": "paragraph", "text": "\n".join(cls._table_texts(block))},
                limit,
            )
        for index, fragment in enumerate(fragments, 1):
            if index > 1 and fragment.get("rows"):
                fragment["rows"][0]["isOverlap"] = True
                for cell in fragment["rows"][0].get("cells", []):
                    cell["isOverlap"] = True
        return fragments

    @classmethod
    def _tail_overlap_blocks(cls, blocks: List[Dict]) -> List[Dict]:
        remaining = REVIEW_CHUNK_OVERLAP_CHARACTERS
        overlap = []
        for block in reversed(blocks):
            text = "\n".join(cls._block_texts([block]))
            if not text:
                continue
            count = _review_character_count(text)
            take = min(remaining, count)
            piece = cls._slice_by_review_chars(text, count - take, count)
            context = {
                "blockId": _derived_id(block.get("sourceBlockId", block["blockId"]), "overlap", len(overlap) + 1),
                "sourceBlockId": block.get("sourceBlockId", block["blockId"]),
                "blockType": "paragraph",
                "paragraphIndex": block.get("paragraphIndex", 0),
                "text": piece,
                "isOverlap": True,
                "core": False,
                "contextOnly": True,
            }
            overlap.insert(0, context)
            remaining -= take
            if remaining <= 0:
                break
        return overlap

    @classmethod
    def _build_review_chunks(cls, snapshot: Dict) -> List[Dict]:
        units = []
        for block in snapshot["blocks"]:
            if block["blockType"] == "table":
                units.extend(cls._split_table_block(block, REVIEW_CHUNK_TARGET_CHARACTERS))
            else:
                units.extend(cls._split_text_block(block, REVIEW_CHUNK_TARGET_CHARACTERS))
        core_chunks = []
        current = []
        current_count = 0
        pending = list(units)
        while pending:
            block = pending.pop(0)
            count = cls._block_character_count(block)
            if current and current_count + count > REVIEW_CHUNK_TARGET_CHARACTERS:
                available = REVIEW_CHUNK_TARGET_CHARACTERS - current_count
                if block["blockType"] != "table" and available > 0:
                    split_units = cls._split_text_unit(block, available)
                    current.append(split_units.pop(0))
                    current_count = REVIEW_CHUNK_TARGET_CHARACTERS
                    core_chunks.append(current)
                    current = []
                    current_count = 0
                    pending = split_units + pending
                    continue
                core_chunks.append(current)
                current = []
                current_count = 0
            current.append(block)
            current_count += count
        if current:
            core_chunks.append(current)
        chunks = []
        for index, core_blocks in enumerate(core_chunks, 1):
            overlap_blocks = cls._tail_overlap_blocks(core_chunks[index - 2]) if index > 1 else []
            chunks.append(cls._make_review_chunk(index, overlap_blocks + core_blocks))
        return chunks

    @classmethod
    def _make_review_chunk(cls, number: int, blocks: List[Dict]) -> Dict:
        review_count = sum(cls._block_character_count(block) for block in blocks)
        core_count = sum(cls._block_core_character_count(block) for block in blocks)
        overlap_count = max(review_count - core_count, 0)
        return {
            "chunkId": "chunk-{0}".format(number),
            "blocks": deepcopy(blocks),
            "sourceText": "\n".join(cls._block_texts(blocks)),
            "reviewCharacterCount": core_count + overlap_count,
            "coreCharacterCount": core_count,
            "overlapCharacterCount": overlap_count,
            "coreRanges": [
                {
                    "sourceBlockId": block.get("sourceBlockId", block["blockId"]),
                    "start": block.get("sourceOffsetStart", 0),
                    "end": block.get("sourceOffsetEnd", cls._block_character_count(block)),
                }
                for block in blocks if block.get("isOverlap") is not True
            ],
            "chunkStrategyVersion": CHUNK_STRATEGY_VERSION,
        }

    def _parse_strict_result(
        self, answer: object, snapshot: Dict, chunk: Optional[Dict] = None
    ) -> Dict:
        chunk = chunk or {
            "chunkId": "chunk-1",
            "blocks": snapshot["blocks"],
        }
        finish_reason = (
            answer.get("finishReason", "")
            if isinstance(answer, dict)
            else getattr(answer, "finishReason", "")
        )
        answer_text = answer.get("answer") if isinstance(answer, dict) else answer
        if finish_reason == "length":
            self._saturated_result("length")
        try:
            payload = json.loads(answer_text) if isinstance(answer_text, str) else None
        except (TypeError, ValueError):
            if self._looks_like_truncated_json(answer_text):
                self._saturated_result("json_truncated")
            payload = None
        if not isinstance(payload, dict):
            self._invalid_result()
        schema_version = payload.get("schemaVersion") if isinstance(payload, dict) else ""
        is_current_schema = schema_version == CHUNK_SCHEMA_VERSION
        required_fields = {
            "schemaVersion",
            "chunkId",
            "summary",
            "enumerationStatus",
            "issues",
        }
        if is_current_schema:
            required_fields.update({"hasMoreIssues", "facts", "crossChecks"})
        if not required_fields.issubset(set(payload)) or set(payload) - (
            required_fields | {"hasMoreIssues", "facts", "crossChecks"}
        ):
            self._invalid_result()
        if (
            payload.get("schemaVersion") not in {LEGACY_CHUNK_SCHEMA_VERSION, CHUNK_SCHEMA_VERSION}
            or payload.get("chunkId") != chunk["chunkId"]
            or not isinstance(payload.get("summary"), str)
            or len(payload.get("summary", "")) > 4000
            or payload.get("enumerationStatus") not in _ENUMERATION_STATUSES
            or not isinstance(payload.get("issues"), list)
            or len(payload.get("issues", [])) > MAX_CHUNK_ISSUES
            or (
                "hasMoreIssues" in payload
                and type(payload.get("hasMoreIssues")) is not bool
            )
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
            item_required = required | {"anchorStart"} if is_current_schema else required
            allowed_item_keys = item_required | ({"anchors"} if is_current_schema else set())
            if (
                not isinstance(item, dict)
                or not item_required.issubset(set(item))
                or not set(item).issubset(allowed_item_keys)
            ):
                self._invalid_result()
            if not all(isinstance(item.get(field), str) for field in required):
                self._invalid_result()
            if is_current_schema and (
                type(item.get("anchorStart")) is not int or item["anchorStart"] < 0
            ):
                self._invalid_result()
            if (
                item.get("category") not in _CATEGORIES
                or item.get("severity") not in _SEVERITIES
                or not item["problem"].strip()
                or len(item["problem"]) > 2000
                or not item["suggestion"].strip()
                or len(item["suggestion"]) > 3000
                or len(item["suggestedRewrite"]) > 4000
            ):
                self._invalid_result()
            evidence_items = [{
                "anchorId": item["anchorId"],
                "anchorStart": item.get("anchorStart"),
                "originalText": item["originalText"],
            }]
            if "anchors" in item:
                if (
                    not isinstance(item["anchors"], list)
                    or not item["anchors"]
                    or any(
                        not isinstance(evidence, dict)
                        or set(evidence) != {"anchorId", "anchorStart", "originalText"}
                        for evidence in item["anchors"]
                    )
                ):
                    self._invalid_result()
                evidence_items.extend(item["anchors"])
            evidence_records = []
            seen_evidence = set()
            for evidence in evidence_items:
                anchor_id = evidence["anchorId"]
                original_text = evidence["originalText"]
                if not isinstance(anchor_id, str) or not isinstance(original_text, str):
                    self._invalid_result()
                anchor = blocks.get(anchor_id, {})
                anchor_start = evidence.get("anchorStart")
                if anchor_start is None:
                    anchor_start = anchor.get("text", "").find(original_text)
                evidence_key = (anchor_id, anchor_start, original_text)
                if evidence_key in seen_evidence:
                    continue
                seen_evidence.add(evidence_key)
                original_end = anchor_start + _review_character_count(original_text)
                is_table_anchor = anchor.get("location") == "table"
                table_anchor_complete = all(
                    anchor.get(field) not in (None, "")
                    for field in (
                        "tableId", "tableIndex", "cellId", "rowIndex", "columnIndex"
                    )
                )
                if (
                    type(anchor_start) is not int
                    or anchor_start < 0
                    or not 0 < len(anchor_id) <= 96
                    or anchor_id not in blocks
                    or not anchor.get("core", True)
                    or not 0 < len(original_text) <= 1000
                    or (is_table_anchor and not table_anchor_complete)
                    or self._slice_by_review_chars(anchor.get("text", ""), anchor_start, original_end) != original_text
                ):
                    self._invalid_result()
                source_offset = anchor.get("sourceOffsetStart", 0) + anchor_start
                source_anchor = {
                    "anchorId": anchor.get("sourceAnchorId", anchor_id),
                    "location": anchor.get("location", "body"),
                    "start": source_offset,
                    "end": source_offset + _review_character_count(original_text),
                    "paragraphIndex": anchor.get("paragraphIndex", 0),
                    "localStart": anchor_start,
                    "localEnd": original_end,
                    "verification": "verified",
                    "originalTextSha256": _sha256_text(original_text),
                }
                if is_table_anchor:
                    for field in (
                        "tableId",
                        "tableIndex",
                        "cellId",
                        "rowIndex",
                        "columnIndex",
                        "rowSpan",
                        "columnSpan",
                        "mergeId",
                    ):
                        if field in anchor and anchor[field] not in (None, ""):
                            source_anchor[field] = anchor[field]
                    source_anchor["tablePath"] = deepcopy(anchor.get("tablePath", []))
                    source_anchor["cellOffsetStart"] = anchor_start
                    source_anchor["cellOffsetEnd"] = original_end
                elif anchor.get("range"):
                    source_anchor["range"] = deepcopy(anchor["range"])
                evidence_records.append({
                    "anchor": anchor,
                    "anchorId": anchor_id,
                    "anchorStart": anchor_start,
                    "originalText": original_text,
                    "originalEnd": original_end,
                    "sourceOffset": source_offset,
                    "sourceAnchor": source_anchor,
                })
            if not evidence_records:
                self._invalid_result()
            anchor_signatures = sorted(
                [
                    {
                        "location": record["sourceAnchor"].get("location", "body"),
                        "anchorId": record["sourceAnchor"].get("anchorId", ""),
                        "start": record["sourceAnchor"].get("start", 0),
                        "end": record["sourceAnchor"].get("end", 0),
                        "tableId": record["sourceAnchor"].get("tableId", ""),
                        "tableIndex": record["sourceAnchor"].get("tableIndex", ""),
                        "tablePath": record["sourceAnchor"].get("tablePath", []),
                        "cellId": record["sourceAnchor"].get("cellId", ""),
                        "rowIndex": record["sourceAnchor"].get("rowIndex", 0),
                        "columnIndex": record["sourceAnchor"].get("columnIndex", 0),
                        "cellOffsetStart": record["sourceAnchor"].get("cellOffsetStart", record["anchorStart"]),
                        "cellOffsetEnd": record["sourceAnchor"].get("cellOffsetEnd", record["originalEnd"]),
                    }
                    for record in evidence_records
                ],
                key=lambda anchor: (
                    anchor["start"], anchor["end"], anchor["location"], anchor["anchorId"]
                ),
            )
            issue_id = "issue-{0}".format(
                _sha256_text(
                    json.dumps(
                        {
                            "snapshot": snapshot["contentSha256"],
                            "category": item["category"],
                            "anchors": anchor_signatures,
                            "semantic": _normalize_issue_semantic(item["problem"]),
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                )[:24]
            )
            duplicate_group_id = "group-{0}".format(
                _sha256_text(
                    json.dumps(
                        {
                            "category": item["category"],
                            "semantic": _normalize_issue_semantic(item["problem"]),
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                )[:24]
            )
            primary = evidence_records[0]
            normalized_item = {
                **item,
                "issueId": issue_id,
                "location": primary["anchor"].get("location", "body"),
                "anchorId": primary["sourceAnchor"].get("anchorId", primary["anchorId"]),
                "chunkAnchorId": primary["anchorId"],
                "anchorStart": primary["anchorStart"],
                "sourceOffset": primary["sourceOffset"],
                "duplicateGroupId": duplicate_group_id,
                "sourceAnchor": primary["sourceAnchor"],
                "sourceAnchors": [record["sourceAnchor"] for record in evidence_records],
                "anchorIds": [record["sourceAnchor"].get("anchorId", record["anchorId"]) for record in evidence_records],
                "anchorVerification": "verified",
            }
            normalized_issues.append(normalized_item)
        facts = self._parse_chunk_facts(payload.get("facts", []), blocks, chunk["chunkId"])
        cross_checks = self._parse_chunk_cross_checks(
            payload.get("crossChecks", []), blocks, chunk["chunkId"]
        )
        saturation_reason = ""
        if payload.get("hasMoreIssues") is True:
            saturation_reason = "has_more_issues"
        elif len(normalized_issues) >= MAX_CHUNK_ISSUES:
            saturation_reason = "issue_limit"
        elif payload.get("enumerationStatus") == "limited":
            saturation_reason = "enumeration_limited"
        return {
            **payload,
            "issues": normalized_issues,
            "facts": facts,
            "crossChecks": cross_checks,
            "_saturationReason": saturation_reason,
        }

    @staticmethod
    def _parse_chunk_facts(items: object, blocks: Dict[str, Dict], chunk_id: str) -> List[Dict]:
        if items is None:
            return []
        if not isinstance(items, list) or len(items) > MAX_CHUNK_FACTS:
            raise AdapterError(
                "FULL_DOCUMENT_REVIEW_RESULT_INVALID",
                "模型返回的分片事实索引格式无效。",
                status_code=502,
            )
        facts = []
        fact_ids = set()
        for item in items:
            if not isinstance(item, dict) or set(item) != {"factId", "kind", "statement", "anchorIds"}:
                FullDocumentReviewService._invalid_result()
            fact_id = item.get("factId")
            kind = item.get("kind")
            statement = item.get("statement")
            anchor_ids = item.get("anchorIds")
            if (
                not isinstance(fact_id, str) or not _SAFE_ID.fullmatch(fact_id)
                or not isinstance(kind, str) or not kind.strip() or len(kind) > 48
                or not isinstance(statement, str) or not statement.strip() or len(statement) > 1200
                or not isinstance(anchor_ids, list) or not anchor_ids
                or not all(isinstance(anchor_id, str) and anchor_id in blocks and blocks[anchor_id].get("core", True) for anchor_id in anchor_ids)
            ):
                FullDocumentReviewService._invalid_result()
            if fact_id in fact_ids:
                FullDocumentReviewService._invalid_result()
            fact_ids.add(fact_id)
            facts.append({
                "factId": _derived_id(chunk_id, "fact", fact_id),
                "kind": kind,
                "statement": statement,
                "anchorIds": [blocks[anchor_id].get("sourceAnchorId", anchor_id) for anchor_id in anchor_ids],
                "chunkAnchorIds": list(anchor_ids),
            })
        return facts

    @staticmethod
    def _parse_chunk_cross_checks(items: object, blocks: Dict[str, Dict], chunk_id: str) -> List[Dict]:
        if items is None:
            return []
        if not isinstance(items, list) or len(items) > MAX_CHUNK_CROSS_CHECKS:
            FullDocumentReviewService._invalid_result()
        checks = []
        check_ids = set()
        for item in items:
            if not isinstance(item, dict) or set(item) != {"checkId", "statement", "anchorIds"}:
                FullDocumentReviewService._invalid_result()
            check_id = item.get("checkId")
            statement = item.get("statement")
            anchor_ids = item.get("anchorIds")
            if (
                not isinstance(check_id, str) or not _SAFE_ID.fullmatch(check_id)
                or not isinstance(statement, str) or not statement.strip() or len(statement) > 1200
                or not isinstance(anchor_ids, list) or not anchor_ids
                or not all(isinstance(anchor_id, str) and anchor_id in blocks and blocks[anchor_id].get("core", True) for anchor_id in anchor_ids)
            ):
                FullDocumentReviewService._invalid_result()
            if check_id in check_ids:
                FullDocumentReviewService._invalid_result()
            check_ids.add(check_id)
            checks.append({
                "checkId": _derived_id(chunk_id, "check", check_id),
                "statement": statement,
                "anchorIds": [blocks[anchor_id].get("sourceAnchorId", anchor_id) for anchor_id in anchor_ids],
                "chunkAnchorIds": list(anchor_ids),
            })
        return checks

    @classmethod
    def _review_anchor_blocks(cls, blocks: List[Dict]) -> Dict[str, Dict]:
        anchors = {}

        def add_table_cells(table: Dict, inherited_overlap: bool = False) -> None:
            for row in table.get("rows", []):
                for cell in row.get("cells", []):
                    overlap = inherited_overlap or cell.get("isOverlap") is True or row.get("isOverlap") is True
                    source_start = int(cell.get("sourceOffsetStart", 0) or 0)
                    source_end = int(
                        cell.get(
                            "sourceOffsetEnd",
                            source_start + _review_character_count(cell.get("text", "")),
                        )
                        or source_start
                    )
                    anchors[cell["cellId"]] = {
                        **cell,
                        "location": "table",
                        "sourceAnchorId": cell.get("sourceCellId", cell["cellId"]),
                        "sourceOffsetStart": source_start,
                        "sourceOffsetEnd": source_end,
                        "tableId": table.get("tableId", ""),
                        "tableIndex": table.get("tableIndex", 0),
                        "tablePath": deepcopy(table.get("tablePath", [])),
                        "rowIndex": cell.get("rowIndex", row.get("rowIndex", 0)),
                        "columnIndex": cell.get("columnIndex", 0),
                        "rowSpan": cell.get("rowSpan", 1),
                        "columnSpan": cell.get("columnSpan", 1),
                        "mergeId": cell.get("mergeId", ""),
                        "core": not overlap,
                    }
            for nested in table.get("nestedTables", []):
                add_table_cells(nested, inherited_overlap or table.get("isOverlap") is True)

        for block in blocks:
            source_start = int(block.get("sourceOffsetStart", 0) or 0)
            source_end = int(
                block.get(
                    "sourceOffsetEnd",
                    source_start + _review_character_count("\n".join(cls._block_texts([block]))),
                )
                or source_start
            )
            anchors[block["blockId"]] = {
                "text": "\n".join(cls._block_texts([block])),
                "location": (
                    "table"
                    if block["blockType"] == "table"
                    else "chapter" if block["blockType"] == "heading" else "body"
                ),
                "sourceAnchorId": block.get("sourceBlockId", block["blockId"]),
                "sourceOffsetStart": source_start,
                "sourceOffsetEnd": source_end,
                "paragraphIndex": block.get("paragraphIndex", 0),
                "range": deepcopy(block.get("range", {})),
                "core": block.get("isOverlap") is not True and block.get("contextOnly") is not True,
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
    def _saturated_result(reason: str) -> None:
        raise AdapterError(
            "FULL_DOCUMENT_REVIEW_OUTPUT_SATURATED",
            "模型输出达到当前分片的枚举边界（{0}）。".format(reason),
            status_code=409,
        )

    @staticmethod
    def _looks_like_truncated_json(answer: object) -> bool:
        if not isinstance(answer, str):
            return False
        value = answer.strip()
        if not value:
            return False
        if value.endswith(("...", "…")):
            return True
        if value.startswith("{") and not value.endswith("}"):
            return True
        if value.startswith("[") and not value.endswith("]"):
            return True
        return False

    @classmethod
    def _build_aggregate_input(cls, snapshot: Dict, parsed_chunks: List[Dict]) -> Dict:
        heading_structure = []
        for block in snapshot.get("blocks", []):
            if block.get("blockType") == "heading":
                heading_structure.append({
                    "blockId": block.get("blockId", ""),
                    "paragraphIndex": block.get("paragraphIndex", 0),
                    "headingLevel": block.get("headingLevel", 0),
                    "text": block.get("text", "")[:400],
                })
        chunks = []
        fact_index = []
        cross_check_index = []
        issue_index = []
        for parsed in parsed_chunks:
            chunk = {
                "chunkId": parsed.get("chunkId", ""),
                "summary": parsed.get("summary", "")[:4000],
            }
            chunks.append(chunk)
            fact_index.extend(
                {
                    "factId": fact.get("factId", ""),
                    "kind": fact.get("kind", ""),
                    "statement": fact.get("statement", "")[:1200],
                    "anchorIds": list(fact.get("anchorIds", [])),
                    "chunkId": parsed.get("chunkId", ""),
                }
                for fact in parsed.get("facts", [])
            )
            cross_check_index.extend(
                {
                    "checkId": check.get("checkId", ""),
                    "statement": check.get("statement", "")[:1200],
                    "anchorIds": list(check.get("anchorIds", [])),
                    "chunkId": parsed.get("chunkId", ""),
                }
                for check in parsed.get("crossChecks", [])
            )
            issue_index.extend(
                {
                    "issueId": issue.get("issueId", ""),
                    "category": issue.get("category", ""),
                    "severity": issue.get("severity", ""),
                    "anchorId": issue.get("anchorId", ""),
                    "problem": issue.get("problem", "")[:240],
                    "chunkId": parsed.get("chunkId", ""),
                }
                for issue in parsed.get("issues", [])
            )
        aggregate_input = {
            "schemaVersion": "word.document_review.full.aggregate.request.v1",
            "documentType": snapshot.get("documentType", ""),
            "reviewPrompt": snapshot.get("reviewPrompt", ""),
            "headingStructure": heading_structure,
            "chunks": chunks,
            "facts": fact_index,
            "crossChecks": cross_check_index,
            "issues": issue_index,
        }
        serialized = json.dumps(aggregate_input, ensure_ascii=False, separators=(",", ":"))
        if _review_character_count(serialized) > MAX_AGGREGATE_INPUT_CHARACTERS:
            raise AdapterError(
                "FULL_DOCUMENT_REVIEW_AGGREGATE_INPUT_TOO_LARGE",
                "全局汇总索引超过当前模型输入预算，未发起汇总请求。",
                status_code=409,
            )
        return aggregate_input

    @staticmethod
    def _parse_aggregate_result(answer: object, aggregate_input: Dict) -> Dict:
        answer_text = answer.get("answer") if isinstance(answer, dict) else answer
        try:
            payload = json.loads(answer_text) if isinstance(answer_text, str) else None
        except (TypeError, ValueError) as exc:
            raise AdapterError(
                "FULL_DOCUMENT_REVIEW_AGGREGATE_INVALID",
                "模型返回的全局汇总不是有效 JSON。",
                status_code=502,
            ) from exc
        if not isinstance(payload, dict) or set(payload) - {"schemaVersion", "summary", "findings"}:
            raise AdapterError(
                "FULL_DOCUMENT_REVIEW_AGGREGATE_INVALID",
                "模型返回的全局汇总字段不符合严格契约。",
                status_code=502,
            )
        if (
            payload.get("schemaVersion") != "word.document_review.full.aggregate.v1"
            or not isinstance(payload.get("summary"), str)
            or len(payload.get("summary", "")) > 4000
            or not isinstance(payload.get("findings"), list)
            or len(payload.get("findings", [])) > 100
        ):
            raise AdapterError(
                "FULL_DOCUMENT_REVIEW_AGGREGATE_INVALID",
                "模型返回的全局汇总内容不符合严格契约。",
                status_code=502,
            )
        issue_ids = {
            issue.get("issueId")
            for chunk in aggregate_input.get("chunks", [])
            for issue in chunk.get("issues", [])
        }
        issue_ids.update(issue.get("issueId") for issue in aggregate_input.get("issues", []))
        fact_ids = {
            fact.get("factId")
            for chunk in aggregate_input.get("chunks", [])
            for fact in chunk.get("facts", [])
        }
        fact_ids.update(fact.get("factId") for fact in aggregate_input.get("facts", []))
        anchor_ids = {
            issue.get("anchorId")
            for chunk in aggregate_input.get("chunks", [])
            for issue in chunk.get("issues", [])
        }
        anchor_ids.update(
            issue.get("anchorId")
            for issue in aggregate_input.get("issues", [])
        )
        anchor_ids.update(
            anchor_id
            for chunk in aggregate_input.get("chunks", [])
            for fact in chunk.get("facts", [])
            for anchor_id in fact.get("anchorIds", [])
        )
        anchor_ids.update(
            anchor_id
            for fact in aggregate_input.get("facts", [])
            for anchor_id in fact.get("anchorIds", [])
        )
        anchor_ids.update(
            anchor_id
            for check in aggregate_input.get("crossChecks", [])
            for anchor_id in check.get("anchorIds", [])
        )
        findings = []
        finding_ids = set()
        for item in payload["findings"]:
            required = {"findingId", "kind", "severity", "summary", "issueIds", "factIds", "anchorIds"}
            if not isinstance(item, dict) or set(item) != required:
                raise AdapterError(
                    "FULL_DOCUMENT_REVIEW_AGGREGATE_INVALID",
                    "全局汇总问题字段不完整。",
                    status_code=502,
                )
            for field in ("issueIds", "factIds", "anchorIds"):
                if not isinstance(item[field], list) or not all(
                    isinstance(value, str) and 0 < len(value) <= 120
                    for value in item[field]
                ):
                    raise AdapterError(
                        "FULL_DOCUMENT_REVIEW_AGGREGATE_INVALID",
                        "全局汇总引用列表格式无效。",
                        status_code=502,
                    )
            if (
                not isinstance(item["findingId"], str) or not _SAFE_ID.fullmatch(item["findingId"])
                or item["severity"] not in _SEVERITIES
                or not isinstance(item["kind"], str) or not _SAFE_ID.fullmatch(item["kind"])
                or not isinstance(item["summary"], str) or not item["summary"].strip() or len(item["summary"]) > 2000
                or not isinstance(item["issueIds"], list) or not all(issue_id in issue_ids for issue_id in item["issueIds"])
                or not isinstance(item["factIds"], list) or not all(fact_id in fact_ids for fact_id in item["factIds"])
                or not isinstance(item["anchorIds"], list) or not all(anchor_id in anchor_ids for anchor_id in item["anchorIds"])
                or not item["issueIds"] and not item["factIds"] and not item["anchorIds"]
            ):
                raise AdapterError(
                    "FULL_DOCUMENT_REVIEW_AGGREGATE_INVALID",
                    "全局汇总引用了未知问题、事实或锚点。",
                    status_code=502,
                )
            if item["findingId"] in finding_ids:
                raise AdapterError(
                    "FULL_DOCUMENT_REVIEW_AGGREGATE_INVALID",
                    "全局汇总包含重复的 findingId。",
                    status_code=502,
                )
            finding_ids.add(item["findingId"])
            findings.append(deepcopy(item))
        return {
            "schemaVersion": payload["schemaVersion"],
            "summary": payload["summary"],
            "findings": findings,
        }

    @staticmethod
    def _build_report(
        snapshot: Dict,
        parsed_chunks: List[Dict],
        limited_ranges: Optional[List[str]] = None,
        aggregate_result: Optional[Dict] = None,
    ) -> Dict:
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
        ordered_issues = sorted(
            unique_issues.values(),
            key=lambda issue: (
                issue.get("sourceAnchor", {}).get("start", issue.get("sourceOffset", 0)),
                issue.get("sourceAnchor", {}).get("end", 0),
                issue.get("issueId", ""),
            ),
        )
        duplicate_groups = {}
        for issue in ordered_issues:
            group_id = issue.get("duplicateGroupId", "")
            if not group_id:
                continue
            duplicate_groups.setdefault(group_id, []).append(issue)
        duplicate_group_summaries = [
            {
                "duplicateGroupId": group_id,
                "category": members[0].get("category", ""),
                "issueIds": [member.get("issueId", "") for member in members],
                "count": len(members),
            }
            for group_id, members in sorted(duplicate_groups.items())
            if len(members) > 1
        ]
        for members in duplicate_groups.values():
            for issue in members:
                issue["duplicateGroupSize"] = len(members)
        initial_chunks = FullDocumentReviewService._build_review_chunks(snapshot)
        overlap_count = sum(item.get("overlapCharacterCount", 0) for item in initial_chunks)
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
                "initialChunkCount": len(initial_chunks),
                "overlapCharacterCount": overlap_count,
                "uniqueCoreCharacterCount": snapshot["reviewCharacterCount"],
                "includedRegions": snapshot["coverage"]["includedRegions"],
                "excludedRegions": snapshot["coverage"]["excludedRegions"],
            },
            "enumerationStatus": enumeration_status,
            "enumerationLimitedRanges": list(limited_ranges or []),
            "chunkStrategyVersion": CHUNK_STRATEGY_VERSION,
            "globalSummary": (aggregate_result or {}).get("summary", ""),
            "globalFindings": deepcopy((aggregate_result or {}).get("findings", [])),
            "duplicateGroups": duplicate_group_summaries,
            "disclaimer": "覆盖完整仅表示声明范围未被静默截断，不承诺检出全部问题。",
            "issues": [
                {**issue, "status": issue.get("status", "open"),
                 "location": issue.get("location", "body")}
                for issue in ordered_issues
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
        duplicate_group_sizes = {}
        for issue in issues:
            group_id = issue.get("duplicateGroupId")
            if group_id:
                duplicate_group_sizes[group_id] = duplicate_group_sizes.get(group_id, 0) + 1
        report["duplicateGroupCount"] = sum(
            1 for count in duplicate_group_sizes.values() if count > 1
        )

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
                try:
                    self._report_path(job_id).unlink(missing_ok=True)
                except OSError:
                    pass
                return None
            if self._wall_clock() >= float(report.get("reportExpiresAt", 0)):
                with self._lock:
                    self._reports.pop(job_id, None)
                try:
                    self._report_path(job_id).unlink(missing_ok=True)
                except OSError:
                    pass
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
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            return None
        with self._lock:
            self._reports[job_id] = report
        return deepcopy(report)

    def _public_report(self, report: Dict) -> Dict:
        public = _sanitize_export_value(report)
        public.pop("issues", None)
        public.pop("reportExpiresAt", None)
        public.pop("reportSha256", None)
        public["issuesEndpoint"] = "issues"
        return public

    def export_report(self, job_id: str, output_format: str) -> object:
        report = _sanitize_export_value(self._require_report(job_id))
        if output_format == "json":
            report.pop("reportExpiresAt", None)
            report.pop("reportSha256", None)
            report["exportSchemaVersion"] = "word.document_review.full.export.v1"
            return report
        if output_format != "markdown":
            raise AdapterError(
                "FULL_DOCUMENT_REVIEW_REPORT_FORMAT_INVALID",
                "全篇审查报告仅支持 json 或 markdown 格式。",
            )
        lines = ["# 全篇审查报告", "", report.get("summary") or "审查已完成。", ""]
        lines.insert(1, "导出版本：word.document_review.full.export.v1")
        lines.append("## 覆盖与统计")
        lines.append("- 审查字符：{0}".format(report.get("coverage", {}).get("reviewedCharacterCount", 0)))
        lines.append("- 问题数量：{0}".format(report.get("issueCount", 0)))
        lines.append("- 重复问题组：{0}".format(report.get("duplicateGroupCount", 0)))
        lines.append("- 问题枚举：{0}".format(report.get("enumerationStatus", "limited")))
        lines.append("")
        if report.get("globalSummary"):
            lines.extend(["## 跨片全局结论", report["globalSummary"], ""])
        for finding in report.get("globalFindings", []):
            lines.extend([
                "### {0} · {1}".format(finding.get("findingId", "全局发现"), finding.get("summary", "")),
                "- 类型：{0}".format(finding.get("kind", "")),
                "- 严重程度：{0}".format(finding.get("severity", "")),
                "- 问题引用：{0}".format(", ".join(finding.get("issueIds", [])) or "无"),
                "- 事实引用：{0}".format(", ".join(finding.get("factIds", [])) or "无"),
                "- 锚点引用：{0}".format(", ".join(finding.get("anchorIds", [])) or "无"),
                "",
            ])
        for index, issue in enumerate(report.get("issues", []), 1):
            lines.extend([
                "## {0}. {1}".format(index, issue.get("problem", "审查问题")),
                "- 问题编号：{0}".format(issue.get("issueId", "")),
                "- 状态：{0}".format(issue.get("status", "open")),
                "- 严重程度：{0}".format(issue.get("severity", "")),
                "- 原文锚点：{0}".format(issue.get("anchorId", "")),
                "- 锚点验证：{0}".format(issue.get("anchorVerification", "unverified")),
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
            if child.name.startswith("job-"):
                job_id = child.name[4:]
                record = self._load_persisted_job(child / "job.json")
                expiry = float((record or {}).get("expiresAt", 0) or 0)
                expired = record is None or (expiry and now >= expiry)
                if expired:
                    try:
                        self._remove_job_data(job_id)
                    except OSError:
                        pass
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
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".private-", dir=str(path.parent)
        )
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, str(path))
            os.chmod(str(path), 0o600)
        except Exception:
            try:
                os.close(descriptor)
            except OSError:
                pass
            try:
                os.unlink(temporary_name)
            except OSError:
                pass
            raise

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

    def _remove_job_data(self, job_id: str) -> None:
        if not _SAFE_ID.fullmatch(str(job_id or "")):
            return
        with self._lock:
            self._job_records.pop(job_id, None)
        path = self._job_dir(job_id)
        if path.exists():
            shutil.rmtree(str(path))


full_document_review_service = FullDocumentReviewService()
full_document_review_service.start_periodic_cleanup()
