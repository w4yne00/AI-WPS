import os
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


PROGRAM_ROOT = Path(__file__).resolve().parents[3]


def _configured_path(name: str) -> Optional[Path]:
    value = os.environ.get(name, "")
    if not value:
        return None
    if any(unicodedata.category(character) == "Cc" for character in value):
        raise ValueError("{0} must not contain control characters".format(name))
    path = Path(value)
    if not path.is_absolute():
        raise ValueError("{0} must be an absolute path".format(name))
    return path


@dataclass(frozen=True)
class RuntimePaths:
    program_root: Path
    state_dir: Path
    config_path: Path
    local_api_key_path: Path
    api_key_dir: Path
    writing_policy_db_path: Path
    backup_dir: Path
    var_dir: Path
    log_dir: Path
    run_dir: Path
    pid_path: Path
    transaction_dir: Path
    shared_state_enabled: bool


def resolve_runtime_paths(program_root: Optional[Path] = None) -> RuntimePaths:
    root = Path(program_root) if program_root is not None else PROGRAM_ROOT
    configured_state_dir = _configured_path("AI_WPS_STATE_DIR")
    configured_backup_dir = _configured_path("AI_WPS_BACKUP_DIR")
    configured_var_dir = _configured_path("AI_WPS_VAR_DIR")

    if configured_state_dir is not None:
        state_dir = configured_state_dir
        layout_root = state_dir.parent
        config_path = state_dir / "adapter.json"
        local_api_key_path = state_dir / "provider_api_key"
        api_key_dir = state_dir / "provider_api_keys"
        writing_policy_db_path = state_dir / "writing_policies.db"
        backup_dir = configured_backup_dir or layout_root / "backups"
        var_dir = configured_var_dir or layout_root / "var"
        shared_state_enabled = True
    else:
        state_dir = root
        config_path = root / "config" / "adapter.json"
        local_api_key_path = root / "run" / "provider_api_key"
        api_key_dir = root / "run" / "provider_api_keys"
        writing_policy_db_path = root / "run" / "writing_policies.db"
        backup_dir = configured_backup_dir or root / "backups"
        var_dir = configured_var_dir or root
        shared_state_enabled = False

    log_dir = var_dir / "logs"
    run_dir = var_dir / "run"
    return RuntimePaths(
        program_root=root,
        state_dir=state_dir,
        config_path=config_path,
        local_api_key_path=local_api_key_path,
        api_key_dir=api_key_dir,
        writing_policy_db_path=writing_policy_db_path,
        backup_dir=backup_dir,
        var_dir=var_dir,
        log_dir=log_dir,
        run_dir=run_dir,
        pid_path=run_dir / "adapter.pid",
        transaction_dir=var_dir / "transactions"
        if shared_state_enabled or configured_var_dir is not None
        else run_dir / "transactions",
        shared_state_enabled=shared_state_enabled,
    )
