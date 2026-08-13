import hashlib
import json
import os
import re
import secrets
import tempfile
import threading
import time
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Dict, Optional

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
SNAPSHOT_TTL_SECONDS = 15 * 60
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,95}$")


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
            "snapshotId": snapshot_id,
            "snapshotTokenSha256": hashlib.sha256(snapshot_token.encode("utf-8")).hexdigest(),
            "createdAt": self._wall_clock(),
            "status": "staged",
            "request": request_data,
            "contentSha256": content_sha256,
            "reviewCharacterCount": len(review_text),
            "paragraphCount": len(paragraphs),
        }
        path = self._snapshot_path(snapshot_id)
        serialized = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        if len(serialized.encode("utf-8")) > MAX_SNAPSHOT_BYTES:
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_TOO_LARGE",
                "确定性格式审查快照不得超过 512 KB。",
                status_code=413,
            )
        self._ensure_staging_root()
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=str(self.staging_root),
                prefix=".format-review-",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                handle.write(serialized)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(str(temporary), str(path))
            os.chmod(str(path), 0o600)
        except OSError as exc:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
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
            snapshot={"request": request, "snapshotId": snapshot_id},
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

    def _snapshot_path(self, snapshot_id: str) -> Path:
        return self.staging_root / (snapshot_id + ".json")

    def _load_snapshot(self, snapshot_id: str) -> Dict:
        with self._lock:
            cached = self._snapshots.get(snapshot_id)
        path = cached.get("path") if cached else self._snapshot_path(snapshot_id)
        if not path.exists():
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_SNAPSHOT_NOT_FOUND",
                "确定性格式审查快照不存在或已过期。",
                status_code=404,
            )
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
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
        path = record.get("path") if record else self._snapshot_path(snapshot_id)
        try:
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


deterministic_format_review_service = DeterministicFormatReviewService()
