#!/usr/bin/env bash
set -euo pipefail

KIT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_ROOT="$(dirname "$KIT_ROOT")"
PYTHON_BIN="${PYTHON_BIN:-python3}"
STATE_DIR="${AI_WPS_STATE_DIR:-$INSTALL_ROOT/state}"
BACKUP_DIR="${AI_WPS_BACKUP_DIR:-$INSTALL_ROOT/backups}"
RELEASE_VERSION="${EXPECTED_VERSION:-0.23.1-alpha}"
TOOL="$KIT_ROOT/adapter_service/tools/runtime_state.py"

[ -f "$TOOL" ] || {
  printf '%s\n' "runtime_state_failed=tool_missing"
  exit 1
}

command_name="${1:-}"
case "$command_name" in
  snapshot)
    reason="${2:-manual_backup}"
    protect_flag=()
    if [ "${3:-}" = "--protect-last-accepted" ]; then
      protect_flag=(--protect-last-accepted)
    elif [ -n "${3:-}" ]; then
      printf '%s\n' "runtime_state_failed=unknown_snapshot_option"
      exit 2
    fi
    exec "$PYTHON_BIN" "$TOOL" snapshot \
      --state-dir "$STATE_DIR" \
      --backup-dir "$BACKUP_DIR" \
      --release-version "$RELEASE_VERSION" \
      --reason "$reason" \
      "${protect_flag[@]}"
    ;;
  migrate)
    legacy_root="${2:-}"
    [ -n "$legacy_root" ] || {
      printf '%s\n' "runtime_state_failed=legacy_root_required"
      exit 2
    }
    exec "$PYTHON_BIN" "$TOOL" migrate \
      --state-dir "$STATE_DIR" \
      --backup-dir "$BACKUP_DIR" \
      --release-version "$RELEASE_VERSION" \
      --legacy-root "$legacy_root"
    ;;
  restore)
    snapshot_id="${2:-}"
    confirmation="${3:-}"
    [ -n "$snapshot_id" ] || {
      printf '%s\n' "runtime_state_failed=snapshot_id_required"
      exit 2
    }
    [ "$confirmation" = "RESTORE_WHOLE_STATE" ] || {
      printf '%s\n' "runtime_state_failed=restore_confirmation_required"
      exit 2
    }
    exec "$PYTHON_BIN" "$TOOL" restore \
      --state-dir "$STATE_DIR" \
      --backup-dir "$BACKUP_DIR" \
      --release-version "$RELEASE_VERSION" \
      --snapshot-id "$snapshot_id" \
      --confirm RESTORE_WHOLE_STATE
    ;;
  *)
    printf '%s\n' \
      "usage: runtime_state.sh snapshot [reason] [--protect-last-accepted] | migrate <legacy-root> | restore <snapshot-id> RESTORE_WHOLE_STATE"
    exit 2
    ;;
esac
