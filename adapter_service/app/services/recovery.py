import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from app.core.runtime_paths import resolve_runtime_paths
from app.services.runtime_state import RuntimeStateManager


_SAFE_VALUE = re.compile(r"^[A-Za-z0-9_.:-]{0,160}$")
_SAFE_SNAPSHOT_ID = re.compile(r"^snapshot-[A-Za-z0-9_.-]+$")
_SAFE_AUDIT_ACTIONS = {"snapshot", "migrate", "restore", "prune"}
_SAFE_AUDIT_STATUSES = {
    "blocked",
    "degraded",
    "pending",
    "ready",
    "recovery",
}


class RecoveryOperationError(RuntimeError):
    def __init__(self, code: str, status: str = "blocked") -> None:
        super().__init__(code)
        self.code = code
        self.status = status


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _safe_value(value: object, fallback: str = "unknown") -> str:
    normalized = str(value or "").strip()
    return normalized if _SAFE_VALUE.fullmatch(normalized) else fallback


class RecoveryOperations:
    def __init__(
        self,
        state_dir: Path,
        backup_dir: Path,
        release_version: str,
    ) -> None:
        self.state_dir = Path(state_dir)
        self.backup_dir = Path(backup_dir)
        self.release_version = _safe_value(release_version)
        self.manager = RuntimeStateManager(
            state_dir=self.state_dir,
            backup_dir=self.backup_dir,
            release_version=self.release_version,
        )

    def backup_status(self) -> Dict:
        verified: List[Dict] = []
        valid: List[Dict] = []
        if not self.backup_dir.is_dir():
            return self._backup_status_payload(verified, valid)
        for snapshot_dir in self.backup_dir.iterdir():
            if (
                not snapshot_dir.is_dir()
                or snapshot_dir.name.startswith(".")
                or not _SAFE_SNAPSHOT_ID.fullmatch(snapshot_dir.name)
            ):
                continue
            try:
                manifest = json.loads(
                    (snapshot_dir / "manifest.json").read_text(encoding="utf-8")
                )
                if (
                    not isinstance(manifest, dict)
                    or manifest.get("snapshotId") != snapshot_dir.name
                ):
                    continue
            except Exception:
                continue
            files = manifest.get("files")
            if not isinstance(files, list) or not (
                manifest.get("copyVerified") is True
                or manifest.get("valid") is True
            ):
                continue
            item = {
                "snapshotId": snapshot_dir.name,
                "createdAt": _safe_value(manifest.get("createdAt"), ""),
                "status": (
                    "ready"
                    if manifest.get("valid") is True
                    else (
                        "recovery"
                        if manifest.get("coreStatus") == "recovery"
                        else "degraded"
                    )
                ),
            }
            verified.append(item)
            if manifest.get("valid") is True:
                valid.append(item)
        return self._backup_status_payload(verified, valid)

    @staticmethod
    def _backup_status_payload(verified: List[Dict], valid: List[Dict]) -> Dict:
        verified.sort(key=lambda item: (item["createdAt"], item["snapshotId"]))
        valid.sort(key=lambda item: (item["createdAt"], item["snapshotId"]))
        return {
            "verifiedCount": len(verified),
            "validCount": len(valid),
            "latestVerified": verified[-1] if verified else None,
            "latestValid": valid[-1] if valid else None,
        }

    def create_read_only_backup(self, current_status: str) -> Dict:
        if current_status != "recovery":
            raise RecoveryOperationError("RECOVERY_MODE_REQUIRED")
        try:
            result = self.manager.create_snapshot("recovery_read_only_backup")
            try:
                backup_status = self.backup_status()
            except Exception:
                latest = {
                    "snapshotId": _safe_value(result.get("snapshotId"), ""),
                    "createdAt": "",
                    "status": _safe_value(result.get("status"), "recovery"),
                }
                backup_status = {
                    "verifiedCount": 1,
                    "validCount": 1 if result.get("valid") is True else 0,
                    "latestVerified": latest,
                    "latestValid": latest if result.get("valid") is True else None,
                    "statusUnavailable": True,
                }
        except Exception:
            raise RecoveryOperationError("RECOVERY_BACKUP_FAILED", "recovery")
        return dict(result, backupStatus=backup_status)

    def build_diagnostics(self, health_snapshot: Dict) -> Dict:
        snapshot = health_snapshot if isinstance(health_snapshot, dict) else {}
        return {
            "generatedAt": _utc_now(),
            "service": _safe_value(snapshot.get("service"), "wps-ai-adapter"),
            "status": _safe_value(snapshot.get("status")),
            "version": _safe_value(snapshot.get("version"), self.release_version),
            "mode": _safe_value(snapshot.get("mode")),
            "subsystems": self._sanitize_subsystems(snapshot.get("subsystems")),
            "operationPolicy": self._sanitize_operation_policy(
                snapshot.get("operationPolicy")
            ),
            "backupStatus": self.backup_status(),
            "recentAudit": self._recent_audit(),
        }

    @staticmethod
    def _sanitize_subsystems(value: object) -> Dict:
        if not isinstance(value, dict):
            return {}
        result = {}
        for name in ("modelConfigurations", "taskRoutes", "writingPolicies"):
            item = value.get(name)
            if not isinstance(item, dict):
                continue
            actions = item.get("allowedActions")
            result[name] = {
                "status": _safe_value(item.get("status")),
                "errorCode": _safe_value(item.get("errorCode"), ""),
                "stage": _safe_value(item.get("stage"), ""),
                "allowedActions": [
                    action
                    for action in (
                        _safe_value(candidate, "")
                        for candidate in (actions if isinstance(actions, list) else [])
                    )
                    if action
                ],
            }
        return result

    @staticmethod
    def _sanitize_operation_policy(value: object) -> Dict:
        policy = value if isinstance(value, dict) else {}
        return {
            name: policy.get(name) is True
            for name in (
                "configurationMutationsAllowed",
                "modelTasksAllowed",
                "writingPolicyMutationsAllowed",
            )
        }

    def _recent_audit(self) -> List[Dict]:
        audit_path = self.backup_dir / "runtime-state-audit.jsonl"
        try:
            lines = audit_path.read_text(encoding="utf-8").splitlines()[-20:]
        except (OSError, UnicodeError):
            return []
        result = []
        for line in lines:
            try:
                item = json.loads(line)
            except Exception:
                continue
            if not isinstance(item, dict):
                continue
            action = str(item.get("action", ""))
            status = str(item.get("status", ""))
            snapshot_id = str(item.get("snapshotId", ""))
            if (
                action not in _SAFE_AUDIT_ACTIONS
                or status not in _SAFE_AUDIT_STATUSES
                or not _SAFE_SNAPSHOT_ID.fullmatch(snapshot_id)
            ):
                continue
            result.append(
                {
                    "timestamp": _safe_value(item.get("timestamp"), ""),
                    "action": action,
                    "status": status,
                    "snapshotId": snapshot_id,
                }
            )
        return result


def get_recovery_operations(release_version: Optional[str] = None) -> RecoveryOperations:
    paths = resolve_runtime_paths()
    return RecoveryOperations(
        state_dir=paths.state_dir,
        backup_dir=paths.backup_dir,
        release_version=release_version or "0.23.1-alpha",
    )
