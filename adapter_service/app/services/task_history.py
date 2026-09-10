import json
import os
import re
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.runtime_paths import resolve_runtime_paths

MAX_HISTORY_ENTRIES_PER_TASK = 20
MAX_HISTORY_ENTRY_BYTES = 5 * 1024 * 1024  # 5 MiB
MAX_TOTAL_HISTORY_BYTES = 100 * 1024 * 1024  # 100 MiB
HISTORY_TTL_SECONDS = 24 * 3600  # 24 hours

HISTORY_ID_PATTERN = re.compile(r"^hist_\d+_[a-f0-9]{8,32}$")
SENSITIVE_KEY_PATTERN = re.compile(
    r"(?i)(api_?key|token|auth|secret|full_?path|raw_?input|request_?body|headers|prompt|user_?instruction|evidence|original_?text|selection)"
)
_HISTORY_LOCK = threading.RLock()


class TaskHistoryError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def canonical_task_type(task_type: str) -> str:
    val = str(task_type or "").strip()
    if val == "word.format_review.deterministic":
        return "word.format_review"
    return val


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _parse_iso(timestamp: str) -> Optional[datetime]:
    try:
        ts = str(timestamp or "").strip()
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def _sanitize_data(data: Any) -> Any:
    if isinstance(data, dict):
        cleaned = {}
        for k, v in data.items():
            if SENSITIVE_KEY_PATTERN.search(str(k)):
                continue
            cleaned[k] = _sanitize_data(v)
        return cleaned
    elif isinstance(data, list):
        return [_sanitize_data(item) for item in data]
    return data


def sanitize_audit_for_history(audit: Any) -> Dict[str, Any]:
    if not isinstance(audit, dict):
        return {}
    sanitized: Dict[str, Any] = {
        "enabled": bool(audit.get("enabled", False)),
        "passed": bool(audit.get("passed", False)),
        "degraded": bool(audit.get("degraded", False)),
        "summary": str(audit.get("summary") or ""),
    }
    if "needsReview" in audit and isinstance(audit["needsReview"], list):
        cleaned_needs_review: List[Dict[str, str]] = []
        for item in audit["needsReview"]:
            if isinstance(item, dict):
                cleaned_needs_review.append({
                    "code": str(item.get("code") or ""),
                    "severity": str(item.get("severity") or ""),
                    "message": str(item.get("message") or ""),
                })
        sanitized["needsReview"] = cleaned_needs_review
    if "expressionSuggestions" in audit and isinstance(audit["expressionSuggestions"], list):
        cleaned_suggestions: List[Dict[str, str]] = []
        for item in audit["expressionSuggestions"]:
            if isinstance(item, dict):
                cleaned_suggestions.append({
                    "code": str(item.get("code") or ""),
                    "message": str(item.get("message") or ""),
                    "suggestion": str(item.get("suggestion") or ""),
                })
        sanitized["expressionSuggestions"] = cleaned_suggestions
    return sanitized


def sanitize_usage_for_history(usage: Any) -> Dict[str, Any]:
    if not isinstance(usage, dict):
        return {}
    pack_names = usage.get("packNames")
    return {
        "scene": str(usage.get("scene") or ""),
        "packNames": [str(name) for name in pack_names] if isinstance(pack_names, list) else [],
    }


def _default_history_dir() -> Path:
    paths = resolve_runtime_paths()
    return paths.var_dir / "history"


class TaskHistoryStore:
    def __init__(self, history_dir: Optional[Path] = None, base_dir: Optional[Path] = None) -> None:
        target_dir = history_dir if history_dir is not None else base_dir
        self.history_dir = Path(target_dir) if target_dir is not None else _default_history_dir()
        if self.history_dir.exists():
            try:
                os.chmod(self.history_dir, 0o700)
            except OSError:
                pass

    def _ensure_dir(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(directory, 0o700)
        except OSError:
            pass
        if self.history_dir.exists():
            try:
                os.chmod(self.history_dir, 0o700)
            except OSError:
                pass

    def _task_dir(self, task_type: str) -> Path:
        canon = canonical_task_type(task_type)
        safe_task = re.sub(r"[^A-Za-z0-9_.-]", "_", str(canon))
        return self.history_dir / safe_task

    def _find_history_file(self, history_id: str) -> Optional[Path]:
        target_id = str(history_id or "").strip()
        if not target_id or not HISTORY_ID_PATTERN.match(target_id):
            return None
        if not self.history_dir.exists():
            return None

        resolved_root = self.history_dir.resolve()
        target_filename = f"{target_id}.json"

        for task_dir in self.history_dir.iterdir():
            if not task_dir.is_dir():
                continue
            candidate = task_dir / target_filename
            try:
                resolved_candidate = candidate.resolve()
                if not str(resolved_candidate).startswith(str(resolved_root)):
                    continue
                if candidate.is_file():
                    return candidate
            except Exception:
                continue
        return None

    def record_success(
        self,
        task_type: str,
        job_id: str,
        result: Dict[str, Any],
        document_display_name: str,
        service_name: str,
        model_name: str,
        completed_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        with _HISTORY_LOCK:
            task_type_str = canonical_task_type(str(task_type or "").strip())
            if not task_type_str:
                raise TaskHistoryError("TASK_TYPE_REQUIRED", "任务功能标识不能为空。")

            cleaned_result = _sanitize_data(result or {})
            timestamp = completed_at or _utc_now()
            entry_id = f"hist_{int(datetime.now(timezone.utc).timestamp())}_{uuid.uuid4().hex[:12]}"

            # Safe document display name (avoid any path separators)
            display_name = os.path.basename(str(document_display_name or "").strip()) or "未命名文档"

            entry = {
                "id": entry_id,
                "taskType": task_type_str,
                "jobId": str(job_id or "").strip(),
                "completedAt": timestamp,
                "documentDisplayName": display_name,
                "serviceName": str(service_name or "").strip(),
                "modelName": str(model_name or "").strip(),
                "result": cleaned_result,
            }

            serialized = json.dumps(entry, ensure_ascii=False, indent=2)
            encoded_bytes = serialized.encode("utf-8")
            if len(encoded_bytes) > MAX_HISTORY_ENTRY_BYTES:
                raise TaskHistoryError(
                    "HISTORY_ENTRY_TOO_LARGE",
                    f"任务结果大小 ({len(encoded_bytes)} 字节) 超过单条归档上限 (5 MiB)，不予归档。",
                )

            task_dir = self._task_dir(task_type_str)
            self._ensure_dir(task_dir)

            # Atomic write with 0o600 permissions
            fd, tmp_file = tempfile.mkstemp(prefix="tmp_hist_", dir=task_dir)
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(encoded_bytes)
                os.chmod(tmp_file, 0o600)
                final_file = task_dir / f"{entry_id}.json"
                os.replace(tmp_file, final_file)
            except Exception:
                if os.path.exists(tmp_file):
                    os.unlink(tmp_file)
                raise

            # Enforce limits & cleanup
            self._cleanup_task_history(task_type_str)
            self._enforce_global_size_limit()

            return entry

    def list_history(self, task_type: str) -> List[Dict[str, Any]]:
        with _HISTORY_LOCK:
            task_type_str = canonical_task_type(str(task_type or "").strip())
            if not task_type_str:
                return []
            self._cleanup_task_history(task_type_str)
            task_dir = self._task_dir(task_type_str)
            if not task_dir.exists():
                return []

            items = []
            for file_path in task_dir.glob("hist_*.json"):
                try:
                    data = json.loads(file_path.read_text(encoding="utf-8"))
                    items.append(data)
                except Exception:
                    continue

            items.sort(key=lambda x: str(x.get("completedAt", "")), reverse=True)
            return items

    def get_history(self, history_id: str) -> Optional[Dict[str, Any]]:
        with _HISTORY_LOCK:
            file_path = self._find_history_file(history_id)
            if file_path is None:
                return None
            try:
                data = json.loads(file_path.read_text(encoding="utf-8"))
                completed_dt = _parse_iso(data.get("completedAt", ""))
                now = datetime.now(timezone.utc)
                if completed_dt is None or (now - completed_dt).total_seconds() > HISTORY_TTL_SECONDS:
                    try:
                        file_path.unlink()
                    except Exception:
                        pass
                    return None
                return data
            except Exception:
                return None

    def delete_history(self, history_id: str) -> bool:
        with _HISTORY_LOCK:
            file_path = self._find_history_file(history_id)
            if file_path is None:
                return False
            try:
                file_path.unlink()
                return True
            except Exception:
                return False

    def clear_history(self, task_type: str) -> int:
        with _HISTORY_LOCK:
            task_type_str = canonical_task_type(str(task_type or "").strip())
            if not task_type_str:
                return 0
            task_dir = self._task_dir(task_type_str)
            if not task_dir.exists():
                return 0

            count = 0
            for file_path in list(task_dir.glob("hist_*.json")):
                try:
                    file_path.unlink()
                    count += 1
                except Exception:
                    pass
            return count

    def _cleanup_task_history(self, task_type: str) -> None:
        task_dir = self._task_dir(task_type)
        if not task_dir.exists():
            return

        now = datetime.now(timezone.utc)
        items = []
        for file_path in list(task_dir.glob("hist_*.json")):
            try:
                data = json.loads(file_path.read_text(encoding="utf-8"))
                completed_dt = _parse_iso(data.get("completedAt", ""))
                if completed_dt is None or (now - completed_dt).total_seconds() > HISTORY_TTL_SECONDS:
                    file_path.unlink()
                    continue
                items.append((data.get("completedAt", ""), file_path))
            except Exception:
                try:
                    file_path.unlink()
                except Exception:
                    pass

        # If count exceeds MAX_HISTORY_ENTRIES_PER_TASK, remove oldest
        if len(items) > MAX_HISTORY_ENTRIES_PER_TASK:
            items.sort(key=lambda x: x[0])  # oldest first
            to_remove = len(items) - MAX_HISTORY_ENTRIES_PER_TASK
            for _, fpath in items[:to_remove]:
                try:
                    fpath.unlink()
                except Exception:
                    pass

    def _enforce_global_size_limit(self) -> None:
        if not self.history_dir.exists():
            return

        all_items = []
        total_size = 0
        for file_path in self.history_dir.glob("*/*.json"):
            try:
                st = file_path.stat()
                total_size += st.st_size
                data = json.loads(file_path.read_text(encoding="utf-8"))
                all_items.append((data.get("completedAt", ""), st.st_size, file_path))
            except Exception:
                continue

        if total_size > MAX_TOTAL_HISTORY_BYTES:
            all_items.sort(key=lambda x: x[0])  # oldest first
            for _, size, fpath in all_items:
                if total_size <= MAX_TOTAL_HISTORY_BYTES:
                    break
                try:
                    fpath.unlink()
                    total_size -= size
                except Exception:
                    pass


_TASK_HISTORY_STORE: Optional[TaskHistoryStore] = None


def get_task_history_store() -> TaskHistoryStore:
    global _TASK_HISTORY_STORE
    with _HISTORY_LOCK:
        if _TASK_HISTORY_STORE is None:
            _TASK_HISTORY_STORE = TaskHistoryStore()
        return _TASK_HISTORY_STORE
