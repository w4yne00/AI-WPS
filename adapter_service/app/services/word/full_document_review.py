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
from typing import Dict, Optional

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
MAX_REVIEW_CHARACTERS = 20000
MAX_REVIEW_BLOCKS = 5000
DEFAULT_STAGING_TTL_SECONDS = 60 * 60
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,95}$")
_CATEGORIES = {"typo", "expression", "logic", "fluency", "professional"}
_SEVERITIES = {"high", "medium", "low"}
_ENUMERATION_STATUSES = {"complete", "limited"}
_EXCLUDED_REGIONS = (
    "tables",
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


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


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
        session_id = "full-review-{0}".format(secrets.token_hex(16))
        upload_token = secrets.token_urlsafe(32)
        session = {
            "sessionId": session_id,
            "snapshotId": session_id,
            "status": "uploading",
            "documentIdSha256": _sha256_text(document_id),
            "documentType": document_type or "technical_solution",
            "reviewPrompt": review_prompt,
            "writingPolicyScene": writing_policy_scene,
            "coverage": {
                "includedRegions": ["body"],
                "excludedRegions": list(_EXCLUDED_REGIONS),
            },
            "uploadTokenSha256": _sha256_text(upload_token),
            "createdAt": self._wall_clock(),
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
        }

    def upload_batch(self, session_id: str, sequence: int, payload: Dict) -> Dict:
        self._require_enabled()
        self._require_object(
            payload, {"uploadToken", "blocks", "characterCount", "contentSha256"}
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
            if sequence != len(session["batches"]):
                raise AdapterError(
                    "FULL_DOCUMENT_REVIEW_BATCH_SEQUENCE_INVALID",
                    "全篇审查正文批次序号不连续。",
                    status_code=409,
                )
            existing_batches = deepcopy(session["batches"])
        blocks = payload.get("blocks")
        if (
            not isinstance(blocks, list)
            or not blocks
            or len(blocks) > MAX_REVIEW_BLOCKS
        ):
            raise AdapterError(
                "FULL_DOCUMENT_REVIEW_BATCH_INVALID", "正文批次不能为空。"
            )
        normalized_blocks = []
        previous_paragraph_index = 0
        seen_ids = {
            item["blockId"]
            for batch in existing_batches
            for item in batch["blocks"]
        }
        for item in blocks:
            if not isinstance(item, dict):
                raise AdapterError(
                    "FULL_DOCUMENT_REVIEW_BATCH_INVALID", "正文内容块格式无效。"
                )
            if set(item) != {"blockId", "blockType", "paragraphIndex", "text"}:
                raise AdapterError(
                    "FULL_DOCUMENT_REVIEW_BLOCK_INVALID", "正文内容块字段无效。"
                )
            block_id = self._required_string(
                item, "blockId", "FULL_DOCUMENT_REVIEW_BLOCK_INVALID", 96
            ).strip()
            block_type = self._required_string(
                item, "blockType", "FULL_DOCUMENT_REVIEW_BLOCK_INVALID", 32
            ).strip()
            text = self._required_string(
                item, "text", "FULL_DOCUMENT_REVIEW_BLOCK_INVALID", MAX_REVIEW_CHARACTERS
            )
            if (
                not _SAFE_ID.fullmatch(block_id)
                or block_id in seen_ids
                or block_type != "paragraph"
                or not text
            ):
                raise AdapterError(
                    "FULL_DOCUMENT_REVIEW_BLOCK_INVALID",
                    "首条全篇审查路径只接受带唯一标识的普通正文段落。",
                )
            seen_ids.add(block_id)
            paragraph_index = self._request_int(
                item.get("paragraphIndex"),
                "FULL_DOCUMENT_REVIEW_BLOCK_INVALID",
                "正文段落序号格式无效。",
            )
            if paragraph_index <= previous_paragraph_index:
                raise AdapterError(
                    "FULL_DOCUMENT_REVIEW_BLOCK_INVALID",
                    "正文段落序号必须是严格递增的正整数。",
                )
            previous_paragraph_index = paragraph_index
            normalized_blocks.append(
                {
                    "blockId": block_id,
                    "blockType": block_type,
                    "paragraphIndex": paragraph_index,
                    "text": text,
                }
            )
        batch_text = "\n".join(item["text"] for item in normalized_blocks)
        character_count = sum(
            _review_character_count(item["text"]) for item in normalized_blocks
        )
        expected_hash = _sha256_text(batch_text)
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
            "blocks": normalized_blocks,
            "characterCount": character_count,
            "contentSha256": expected_hash,
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
            session["status"] = "uploading"
        return {
            "sessionId": session_id,
            "sequence": sequence,
            "status": "uploaded",
            "reviewCharacterCount": total_count,
        }

    def commit_snapshot(self, session_id: str, payload: Dict) -> Dict:
        self._require_enabled()
        self._require_object(payload, {
            "uploadToken", "batchCount", "reviewCharacterCount", "contentSha256",
            "verificationSha256"
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
        source_text = "\n".join(item["text"] for item in blocks)
        character_count = sum(_review_character_count(item["text"]) for item in blocks)
        digest = _sha256_text(source_text)
        valid = (
            len(snapshot_data["batches"]) == 1
            and self._request_int(
                payload.get("batchCount"),
                "FULL_DOCUMENT_REVIEW_COMMIT_INVALID",
                "快照批次数格式无效。",
            )
            == 1
            and self._request_int(
                payload.get("reviewCharacterCount"),
                "FULL_DOCUMENT_REVIEW_COMMIT_INVALID",
                "快照字符数格式无效。",
            )
            == character_count
            and self._required_string(
                payload, "contentSha256", "FULL_DOCUMENT_REVIEW_COMMIT_INVALID", 64
            ) == digest
            and self._required_string(
                payload, "verificationSha256", "FULL_DOCUMENT_REVIEW_COMMIT_INVALID", 64
            ) == digest
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
        snapshot_token = secrets.token_urlsafe(32)
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
            "status": "committed",
            "uploadTokenSha256": "",
            "snapshotTokenSha256": _sha256_text(snapshot_token),
            "sourceText": source_text,
            "blocks": blocks,
            "reviewCharacterCount": character_count,
            "contentSha256": digest,
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
            "status": "committed",
            "reviewCharacterCount": character_count,
            "contentSha256": digest,
            "chunkCount": 1,
            "snapshotToken": snapshot_token,
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
        self._require_object(payload, {"snapshotId", "snapshotToken", "clientJobId"})
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
            if session.get("status") != "committed":
                raise AdapterError(
                    "FULL_DOCUMENT_REVIEW_SNAPSHOT_STATE_INVALID",
                    "全篇审查快照状态不允许当前操作。",
                    status_code=409,
                )
            self._verify_snapshot_token(session, {"snapshotToken": snapshot_token})
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
                    "MODEL_CONFIG_INCOMPLETE",
                    "MODEL_DIRECT_REQUIRED",
                },
                public_metadata={
                    "reviewMode": "full", "snapshotId": snapshot_id, "chunkCount": 1,
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
                    session["status"] = "committed"
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
        result = job.pop("result", None)
        job["reportAvailable"] = bool(
            job.get("status") == "completed" and isinstance(result, dict)
        )
        if isinstance(result, dict):
            job["coverage"] = result.get("coverage", {})
            job["enumerationStatus"] = result.get("enumerationStatus", "")
            job["issueCount"] = len(result.get("issues", []))
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
        if job.get("status") != "completed" or not isinstance(job.get("result"), dict):
            raise AdapterError(
                "FULL_DOCUMENT_REVIEW_REPORT_NOT_AVAILABLE",
                "全篇审查尚未生成可用的结构化报告。",
                status_code=409,
            )
        return job["result"]

    def _run_job(self, snapshot: Dict, progress) -> Dict:
        job_id = str(snapshot.get("jobId", ""))
        try:
            progress("provider_processing")
            answer = self.provider_client.full_document_review_chunk(
                snapshot["sourceText"],
                snapshot.get("traceId", ""),
                "chunk-1",
                snapshot["documentType"],
                snapshot["reviewPrompt"],
                snapshot["taskAuth"],
                correction=False,
                blocks=snapshot["blocks"],
            )
            self._raise_if_cancelled(job_id)
            try:
                parsed = self._parse_strict_result(answer, snapshot)
            except AdapterError:
                self._raise_if_cancelled(job_id)
                corrected = self.provider_client.full_document_review_chunk(
                    snapshot["sourceText"],
                    snapshot.get("traceId", ""),
                    "chunk-1",
                    snapshot["documentType"],
                    snapshot["reviewPrompt"],
                    snapshot["taskAuth"],
                    correction=True,
                    blocks=snapshot["blocks"],
                )
                self._raise_if_cancelled(job_id)
                parsed = self._parse_strict_result(corrected, snapshot)
            self._raise_if_cancelled(job_id)
            progress("parsing")
            return self._build_report(snapshot, parsed)
        finally:
            self._remove_snapshot(str(snapshot.get("snapshotId", "")))

    def _parse_strict_result(self, answer: object, snapshot: Dict) -> Dict:
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
            or payload.get("chunkId") != "chunk-1"
            or not isinstance(payload.get("summary"), str)
            or len(payload.get("summary", "")) > 4000
            or payload.get("enumerationStatus") not in _ENUMERATION_STATUSES
            or not isinstance(payload.get("issues"), list)
            or len(payload.get("issues", [])) > 200
        ):
            self._invalid_result()
        blocks = {item["blockId"]: item for item in snapshot["blocks"]}
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
            normalized_issues.append({"issueId": issue_id, **item})
        return {**payload, "issues": normalized_issues}

    @staticmethod
    def _invalid_result() -> None:
        raise AdapterError(
            "FULL_DOCUMENT_REVIEW_RESULT_INVALID",
            "模型返回结果不符合版本化全篇审查 JSON 契约，未生成报告。",
            status_code=502,
        )

    @staticmethod
    def _build_report(snapshot: Dict, parsed: Dict) -> Dict:
        paragraph_count = len(snapshot["blocks"])
        return {
            "schemaVersion": REPORT_SCHEMA_VERSION,
            "reviewMode": "full",
            "snapshot": {
                "snapshotId": snapshot["snapshotId"],
                "contentSha256": snapshot["contentSha256"],
                "committedAt": snapshot["committedAt"],
            },
            "summary": parsed["summary"],
            "coverage": {
                "status": "complete",
                "reviewedCharacterCount": snapshot["reviewCharacterCount"],
                "reviewedParagraphCount": paragraph_count,
                "reviewedTableCount": 0,
                "reviewedCellCount": 0,
                "includedRegions": snapshot["coverage"]["includedRegions"],
                "excludedRegions": snapshot["coverage"]["excludedRegions"],
            },
            "enumerationStatus": parsed["enumerationStatus"],
            "disclaimer": "覆盖完整仅表示声明范围未被静默截断，不承诺检出全部问题。",
            "issues": parsed["issues"],
        }

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
        for child in children:
            if (
                child.is_symlink()
                or not child.is_dir()
                or not _SAFE_ID.fullmatch(child.name)
            ):
                continue
            try:
                expired = now - child.stat().st_mtime > self._staging_ttl_seconds
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
