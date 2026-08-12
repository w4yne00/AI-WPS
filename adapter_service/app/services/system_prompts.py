import hashlib
import json
from pathlib import Path
from typing import List, Optional


DEFAULT_SYSTEM_PROMPT_ROOT = Path(__file__).resolve().parents[2] / "system_prompts"


class SystemPromptError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class SystemPromptStore:
    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = Path(root or DEFAULT_SYSTEM_PROMPT_ROOT)

    def load(self, task_type: str) -> dict:
        manifest = self._manifest()
        item = manifest.get("tasks", {}).get(str(task_type))
        return self._load_item(str(task_type), item)

    def load_stage(self, stage_type: str) -> dict:
        manifest = self._manifest()
        item = manifest.get("stages", {}).get(str(stage_type))
        return self._load_item(str(stage_type), item)

    def _load_item(self, item_type: str, item: object) -> dict:
        if not isinstance(item, dict):
            raise SystemPromptError(
                "SYSTEM_PROMPT_TASK_UNKNOWN", "当前任务阶段没有可用的 System Prompt。"
            )
        filename = str(item.get("file", "")).strip()
        expected_hash = str(item.get("sha256", "")).strip().lower()
        version = str(item.get("version", "")).strip()
        if not filename or Path(filename).name != filename or not expected_hash or not version:
            raise SystemPromptError(
                "SYSTEM_PROMPT_MANIFEST_INVALID", "System Prompt 清单格式无效。"
            )
        path = self.root / filename
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise SystemPromptError(
                "SYSTEM_PROMPT_MISSING", "任务 System Prompt 缺失，请重新安装当前版本。"
            ) from exc
        actual_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if actual_hash != expected_hash:
            raise SystemPromptError(
                "SYSTEM_PROMPT_DAMAGED", "任务 System Prompt 校验失败，请重新安装当前版本。"
            )
        return {
            "taskType": item_type,
            "version": version,
            "file": filename,
            "sha256": actual_hash,
            "hashPrefix": actual_hash[:12],
            "content": content.strip(),
        }

    def metadata(self, task_type: str) -> dict:
        loaded = self.load(task_type)
        return {key: value for key, value in loaded.items() if key != "content"}

    def list_metadata(self) -> List[dict]:
        manifest = self._manifest()
        return [
            self.metadata(task_type)
            for task_type in sorted(manifest.get("tasks", {}))
        ]

    def _manifest(self) -> dict:
        path = self.root / "manifest.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SystemPromptError(
                "SYSTEM_PROMPT_MANIFEST_INVALID", "System Prompt 清单缺失或损坏。"
            ) from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("tasks"), dict):
            raise SystemPromptError(
                "SYSTEM_PROMPT_MANIFEST_INVALID", "System Prompt 清单格式无效。"
            )
        return payload
