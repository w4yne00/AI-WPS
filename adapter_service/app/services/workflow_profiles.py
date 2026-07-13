import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from app.core.config import DEFAULT_CONFIG_PATH, load_config_payload, save_config_payload


SUPPORTED_WORKFLOW_TASKS = (
    "word.smart_write",
    "word.smart_imitation",
    "word.document_review",
    "word.format_review",
    "excel.analysis",
    "ppt.slide_assistant",
)
MAX_PROFILES_PER_TASK = 20
MAX_PROFILE_NAME_LENGTH = 40
MAX_PROFILE_NOTE_LENGTH = 200
DEFAULT_PROFILE_KEY_DIR = Path(__file__).resolve().parents[3] / "run" / "provider_api_keys"
_SAFE_KEY_REF = re.compile(r"^[A-Za-z0-9_.-]+$")
_STORE_LOCK = threading.RLock()


class WorkflowProfileError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class WorkflowProfileStore:
    def __init__(self, config_path: Path = DEFAULT_CONFIG_PATH, key_dir: Path = DEFAULT_PROFILE_KEY_DIR) -> None:
        self.config_path = Path(config_path)
        self.key_dir = Path(key_dir)

    def list_for_task(self, task_type: str) -> dict:
        task = self._validate_task_type(task_type)
        with _STORE_LOCK:
            if not self.config_path.exists():
                return {
                    "taskType": task,
                    "activeProfileId": "",
                    "profileCount": 0,
                    "profiles": [],
                }
            payload = load_config_payload(self.config_path)
            changed = self._migrate_legacy_task(payload, task)
            if changed:
                save_config_payload(payload, self.config_path)
            profiles = [
                self._sanitize_profile(profile)
                for profile in self._profile_map(payload).values()
                if profile.get("taskType") == task
            ]
            profiles.sort(key=lambda item: (item.get("createdAt", ""), item["id"]))
            active_id = str(self._active_map(payload).get(task, ""))
            if not any(item["id"] == active_id for item in profiles):
                active_id = ""
            return {
                "taskType": task,
                "activeProfileId": active_id,
                "profileCount": len(profiles),
                "profiles": profiles,
            }

    def create_profile(
        self,
        task_type: str,
        name: str,
        api_key: str,
        note: str = "",
        activate: bool = False,
    ) -> dict:
        task = self._validate_task_type(task_type)
        clean_name = self._validate_name(name)
        clean_note = self._validate_note(note)
        clean_key = self._validate_api_key(api_key)
        with _STORE_LOCK:
            payload = load_config_payload(self.config_path)
            self._migrate_legacy_task(payload, task)
            profiles = self._profile_map(payload)
            task_profiles = [item for item in profiles.values() if item.get("taskType") == task]
            if len(task_profiles) >= MAX_PROFILES_PER_TASK:
                raise WorkflowProfileError(
                    "WORKFLOW_PROFILE_LIMIT",
                    "每个功能最多保存 {0} 个工作流配置。".format(MAX_PROFILES_PER_TASK),
                )
            self._ensure_unique_name(task_profiles, clean_name)
            token = uuid.uuid4().hex
            profile_id = "profile_{0}".format(token)
            api_key_ref = "workflow_{0}".format(token)
            now = _utc_now()
            profile = {
                "id": profile_id,
                "taskType": task,
                "name": clean_name,
                "apiKeyRef": api_key_ref,
                "note": clean_note,
                "createdAt": now,
                "updatedAt": now,
            }
            self._write_key(api_key_ref, clean_key)
            profiles[profile_id] = profile
            payload["workflowProfiles"] = profiles
            if activate:
                self._set_active(payload, profile)
            save_config_payload(payload, self.config_path)
            return self._sanitize_profile(profile)

    def update_profile(self, profile_id: str, name: str, note: str = "") -> dict:
        clean_name = self._validate_name(name)
        clean_note = self._validate_note(note)
        with _STORE_LOCK:
            payload = load_config_payload(self.config_path)
            profiles = self._profile_map(payload)
            profile = self._require_profile(profiles, profile_id)
            task_profiles = [
                item
                for item in profiles.values()
                if item.get("taskType") == profile["taskType"] and item.get("id") != profile["id"]
            ]
            self._ensure_unique_name(task_profiles, clean_name)
            profile["name"] = clean_name
            profile["note"] = clean_note
            profile["updatedAt"] = _utc_now()
            profiles[profile["id"]] = profile
            payload["workflowProfiles"] = profiles
            save_config_payload(payload, self.config_path)
            return self._sanitize_profile(profile)

    def replace_api_key(self, profile_id: str, api_key: str) -> dict:
        clean_key = self._validate_api_key(api_key)
        with _STORE_LOCK:
            payload = load_config_payload(self.config_path)
            profiles = self._profile_map(payload)
            profile = self._require_profile(profiles, profile_id)
            self._write_key(profile["apiKeyRef"], clean_key)
            profile["updatedAt"] = _utc_now()
            profiles[profile["id"]] = profile
            payload["workflowProfiles"] = profiles
            save_config_payload(payload, self.config_path)
            return self._sanitize_profile(profile)

    def activate_profile(self, profile_id: str) -> dict:
        with _STORE_LOCK:
            payload = load_config_payload(self.config_path)
            profiles = self._profile_map(payload)
            profile = self._require_profile(profiles, profile_id)
            if not self._key_exists(profile.get("apiKeyRef", "")):
                raise WorkflowProfileError("WORKFLOW_PROFILE_KEY_MISSING", "该工作流尚未配置 API Key。")
            self._set_active(payload, profile)
            save_config_payload(payload, self.config_path)
            return self.list_for_task(profile["taskType"])

    def delete_profile(self, profile_id: str) -> dict:
        with _STORE_LOCK:
            payload = load_config_payload(self.config_path)
            profiles = self._profile_map(payload)
            profile = self._require_profile(profiles, profile_id)
            active_id = str(self._active_map(payload).get(profile["taskType"], ""))
            if active_id == profile["id"]:
                raise WorkflowProfileError(
                    "WORKFLOW_PROFILE_ACTIVE",
                    "当前工作流不能删除，请先切换到其他工作流。",
                )
            profiles.pop(profile["id"], None)
            payload["workflowProfiles"] = profiles
            save_config_payload(payload, self.config_path)
            self._delete_key(profile.get("apiKeyRef", ""))
            return self.list_for_task(profile["taskType"])

    def get_active_profile(self, task_type: str, migrate: bool = True) -> Optional[dict]:
        task = self._validate_task_type(task_type)
        with _STORE_LOCK:
            if not self.config_path.exists():
                return None
            payload = load_config_payload(self.config_path)
            if migrate and self._migrate_legacy_task(payload, task):
                save_config_payload(payload, self.config_path)
            active_id = str(self._active_map(payload).get(task, ""))
            profile = self._profile_map(payload).get(active_id)
            if not isinstance(profile, dict) or profile.get("taskType") != task:
                return None
            return self._sanitize_profile(profile)

    def save_legacy_task_api_key(self, task_type: str, api_key_ref: str, api_key: str) -> dict:
        task = self._validate_task_type(task_type)
        clean_ref = self._validate_key_ref(api_key_ref)
        clean_key = self._validate_api_key(api_key)
        with _STORE_LOCK:
            payload = load_config_payload(self.config_path)
            self._migrate_legacy_task(payload, task)
            profiles = self._profile_map(payload)
            active_id = str(self._active_map(payload).get(task, ""))
            profile = profiles.get(active_id)
            now = _utc_now()
            if not isinstance(profile, dict) or profile.get("taskType") != task:
                profile_id = "profile_{0}".format(uuid.uuid4().hex)
                profile = {
                    "id": profile_id,
                    "taskType": task,
                    "name": "当前配置",
                    "apiKeyRef": clean_ref,
                    "note": "",
                    "createdAt": now,
                    "updatedAt": now,
                }
                profiles[profile_id] = profile
            else:
                old_ref = str(profile.get("apiKeyRef", ""))
                profile["apiKeyRef"] = clean_ref
                profile["updatedAt"] = now
                if old_ref and old_ref != clean_ref and old_ref.startswith("workflow_"):
                    self._delete_key(old_ref)
            self._write_key(clean_ref, clean_key)
            payload["workflowProfiles"] = profiles
            self._set_active(payload, profile)
            save_config_payload(payload, self.config_path)
            return self.list_for_task(task)

    def clear_active_api_key(self, task_type: str) -> dict:
        task = self._validate_task_type(task_type)
        with _STORE_LOCK:
            payload = load_config_payload(self.config_path)
            self._migrate_legacy_task(payload, task)
            active_id = str(self._active_map(payload).get(task, ""))
            profile = self._profile_map(payload).get(active_id)
            if isinstance(profile, dict) and profile.get("taskType") == task:
                self._delete_key(profile.get("apiKeyRef", ""))
            return self.list_for_task(task)

    def _migrate_legacy_task(self, payload: dict, task_type: str) -> bool:
        profiles = self._profile_map(payload)
        if any(item.get("taskType") == task_type for item in profiles.values()):
            return False
        refs = payload.get("taskApiKeyRefs", {})
        if not isinstance(refs, dict):
            return False
        api_key_ref = str(refs.get(task_type, "")).strip()
        if not api_key_ref or not _SAFE_KEY_REF.fullmatch(api_key_ref):
            return False
        now = _utc_now()
        profile_id = "profile_{0}".format(uuid.uuid4().hex)
        profile = {
            "id": profile_id,
            "taskType": task_type,
            "name": "当前配置",
            "apiKeyRef": api_key_ref,
            "note": "由原任务级 API Key 自动迁移",
            "createdAt": now,
            "updatedAt": now,
        }
        profiles[profile_id] = profile
        payload["workflowProfiles"] = profiles
        active = self._active_map(payload)
        active[task_type] = profile_id
        payload["activeWorkflowProfiles"] = active
        return True

    def _set_active(self, payload: dict, profile: dict) -> None:
        active = self._active_map(payload)
        active[profile["taskType"]] = profile["id"]
        payload["activeWorkflowProfiles"] = active
        refs = payload.get("taskApiKeyRefs", {})
        if not isinstance(refs, dict):
            refs = {}
        refs[profile["taskType"]] = profile["apiKeyRef"]
        payload["taskApiKeyRefs"] = refs

    def _sanitize_profile(self, profile: dict) -> dict:
        return {
            "id": str(profile.get("id", "")),
            "taskType": str(profile.get("taskType", "")),
            "name": str(profile.get("name", "")),
            "apiKeyRef": str(profile.get("apiKeyRef", "")),
            "note": str(profile.get("note", "")),
            "createdAt": str(profile.get("createdAt", "")),
            "updatedAt": str(profile.get("updatedAt", "")),
            "keyConfigured": self._key_exists(profile.get("apiKeyRef", "")),
        }

    @staticmethod
    def _profile_map(payload: dict) -> Dict[str, dict]:
        source = payload.get("workflowProfiles", {})
        if not isinstance(source, dict):
            return {}
        profiles = {}
        for profile_id, item in source.items():
            if not isinstance(item, dict):
                continue
            normalized_id = str(item.get("id", profile_id)).strip()
            task_type = str(item.get("taskType", "")).strip()
            api_key_ref = str(item.get("apiKeyRef", "")).strip()
            if not normalized_id or task_type not in SUPPORTED_WORKFLOW_TASKS:
                continue
            if not api_key_ref or not _SAFE_KEY_REF.fullmatch(api_key_ref):
                continue
            copied = dict(item)
            copied["id"] = normalized_id
            copied["taskType"] = task_type
            copied["apiKeyRef"] = api_key_ref
            profiles[normalized_id] = copied
        return profiles

    @staticmethod
    def _active_map(payload: dict) -> Dict[str, str]:
        source = payload.get("activeWorkflowProfiles", {})
        if not isinstance(source, dict):
            return {}
        return {str(task): str(profile_id) for task, profile_id in source.items()}

    @staticmethod
    def _require_profile(profiles: Dict[str, dict], profile_id: str) -> dict:
        normalized_id = str(profile_id).strip()
        profile = profiles.get(normalized_id)
        if not isinstance(profile, dict):
            raise WorkflowProfileError("WORKFLOW_PROFILE_NOT_FOUND", "未找到指定的工作流配置。")
        return profile

    @staticmethod
    def _validate_task_type(task_type: str) -> str:
        task = str(task_type).strip()
        if task not in SUPPORTED_WORKFLOW_TASKS:
            raise WorkflowProfileError("WORKFLOW_PROFILE_TASK_UNSUPPORTED", "不支持的任务类型。")
        return task

    @staticmethod
    def _validate_name(name: str) -> str:
        clean_name = str(name).strip()
        if not clean_name:
            raise WorkflowProfileError("WORKFLOW_PROFILE_NAME_REQUIRED", "请输入工作流名称。")
        if len(clean_name) > MAX_PROFILE_NAME_LENGTH:
            raise WorkflowProfileError(
                "WORKFLOW_PROFILE_NAME_TOO_LONG",
                "工作流名称不能超过 {0} 个字符。".format(MAX_PROFILE_NAME_LENGTH),
            )
        return clean_name

    @staticmethod
    def _validate_note(note: str) -> str:
        clean_note = str(note or "").strip()
        if len(clean_note) > MAX_PROFILE_NOTE_LENGTH:
            raise WorkflowProfileError(
                "WORKFLOW_PROFILE_NOTE_TOO_LONG",
                "工作流备注不能超过 {0} 个字符。".format(MAX_PROFILE_NOTE_LENGTH),
            )
        return clean_note

    @staticmethod
    def _validate_api_key(api_key: str) -> str:
        clean_key = str(api_key).strip()
        if not clean_key:
            raise WorkflowProfileError("WORKFLOW_PROFILE_KEY_REQUIRED", "请输入 API Key。")
        return clean_key

    @staticmethod
    def _validate_key_ref(api_key_ref: str) -> str:
        clean_ref = str(api_key_ref).strip()
        if not clean_ref or not _SAFE_KEY_REF.fullmatch(clean_ref):
            raise WorkflowProfileError("WORKFLOW_PROFILE_KEY_REF_INVALID", "API Key 引用格式无效。")
        return clean_ref

    @staticmethod
    def _ensure_unique_name(profiles, name: str) -> None:
        target = name.casefold()
        if any(str(item.get("name", "")).strip().casefold() == target for item in profiles):
            raise WorkflowProfileError("WORKFLOW_PROFILE_NAME_DUPLICATE", "该功能下的工作流名称已存在。")

    def _key_path(self, api_key_ref: str) -> Path:
        safe_ref = self._validate_key_ref(api_key_ref)
        return self.key_dir / safe_ref

    def _key_exists(self, api_key_ref: str) -> bool:
        try:
            path = self._key_path(str(api_key_ref))
        except WorkflowProfileError:
            return False
        return path.exists() and bool(path.read_text(encoding="utf-8").strip())

    def _write_key(self, api_key_ref: str, api_key: str) -> None:
        path = self._key_path(api_key_ref)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.parent / ".{0}.{1}.tmp".format(path.name, uuid.uuid4().hex)
        try:
            temporary.write_text(api_key.strip() + "\n", encoding="utf-8")
            os.chmod(str(temporary), 0o600)
            os.replace(str(temporary), str(path))
            os.chmod(str(path), 0o600)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _delete_key(self, api_key_ref: str) -> None:
        try:
            path = self._key_path(str(api_key_ref))
        except WorkflowProfileError:
            return
        if path.exists():
            path.unlink()
