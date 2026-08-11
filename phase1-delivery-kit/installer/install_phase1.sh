#!/usr/bin/env bash
set -euo pipefail

DELIVERY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
PORT="${PORT:-18100}"
TARGET_USER_ARG=""
TARGET_UID_ARG=""
TARGET_HOME_ARG=""
WPS_JSADDONS_DIR_ARG=""
ACTIVATE_RECOVERY="0"

WORD_PLUGIN_NAME="wps-ai-assistant_1.0.0"
EXCEL_PLUGIN_NAME="wps-ai-assistant-et_1.0.0"
PPT_PLUGIN_NAME="wps-ai-assistant-wpp_1.0.0"
WORD_PLUGIN_SOURCE="$DELIVERY_ROOT/packages/$WORD_PLUGIN_NAME"
EXCEL_PLUGIN_SOURCE="$DELIVERY_ROOT/packages/$EXCEL_PLUGIN_NAME"
PPT_PLUGIN_SOURCE="$DELIVERY_ROOT/packages/$PPT_PLUGIN_NAME"
ADAPTER_SOURCE="$DELIVERY_ROOT/packages/adapter-start-kit"
PIP_BOOTSTRAP_DIR="$DELIVERY_ROOT/packages/kylin-v10-arm-py38-pip-bootstrap"
RUNTIME_DEPS_DIR="$DELIVERY_ROOT/packages/kylin-v10-arm-py38"
PUBLISH_SOURCE="$DELIVERY_ROOT/wps-jsaddons/publish.xml"
RELEASE_MANIFEST_SOURCE="$DELIVERY_ROOT/release-manifest.json"
TRANSACTION_TOOL="$DELIVERY_ROOT/installer/release_transaction.py"
ADAPTER_TARGET=""
STATE_DIR=""
BACKUP_DIR=""
VAR_DIR=""
RELEASE_VERSION="0.23.1-alpha"
PREVIOUS_RELEASE_VERSION="legacy"
PREVIOUS_SNAPSHOT_ID=""
CANDIDATE_SNAPSHOT_ID=""
TRANSACTION_LOG=""
SYSTEMD_SERVICE_PRESENT="0"
SYSTEMD_WAS_ACTIVE="0"
SYSTEMD_SERVICE_NAME="${SERVICE_NAME:-ai-wps-adapter.service}"
SYSTEMD_SERVICE_FILE="${AI_WPS_SYSTEMD_SERVICE_FILE:-/etc/systemd/system/$SYSTEMD_SERVICE_NAME}"
SYSTEMD_HANDOFF_FILE=""
SYSTEMD_UNIT_BACKUP="${AI_WPS_SYSTEMD_UNIT_BACKUP:-${SYSTEMD_SERVICE_FILE}.ai-wps.previous}"
CURRENT_INSTALL_PRESENT="0"
CURRENT_INSTALL_READY="0"
RUNTIME_BACKUP_VERIFIED="0"
CANDIDATE_HEALTH_STATUS=""
CANDIDATE_RECOVERY_SUMMARY=""
PRESERVE_RECOVERY_CANDIDATE="0"

log() {
  printf '%s\n' "$*"
}

fail() {
  log "install_failed=$*"
  exit 1
}

parse_arguments() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --target-user)
        [ "$#" -ge 2 ] || fail "target_user_value_required"
        TARGET_USER_ARG="$2"
        shift 2
        ;;
      --target-uid)
        [ "$#" -ge 2 ] || fail "target_uid_value_required"
        TARGET_UID_ARG="$2"
        shift 2
        ;;
      --target-home)
        [ "$#" -ge 2 ] || fail "target_home_value_required"
        TARGET_HOME_ARG="$2"
        shift 2
        ;;
      --wps-jsaddons-dir)
        [ "$#" -ge 2 ] || fail "wps_jsaddons_dir_value_required"
        WPS_JSADDONS_DIR_ARG="$2"
        shift 2
        ;;
      --activate-recovery)
        ACTIVATE_RECOVERY="1"
        shift
        ;;
      *)
        fail "unknown_argument value=$1"
        ;;
    esac
  done
}

probe_current_install_readiness() {
  local ready_body=""
  if [ -e "$ADAPTER_TARGET" ] || [ -L "$ADAPTER_TARGET" ]; then
    CURRENT_INSTALL_PRESENT="1"
  else
    CURRENT_INSTALL_PRESENT="0"
  fi
  if [ "$CURRENT_INSTALL_PRESENT" = "1" ]; then
    ready_body="$(curl -fsS "http://127.0.0.1:${PORT}/health/ready" 2>/dev/null || true)"
    ready_body="$(printf '%s' "$ready_body" | tr -d '[:space:]')"
    case "$ready_body" in
      *'"status":"ready"'*|*'"status":"degraded"'*)
        CURRENT_INSTALL_READY="1"
        ;;
      *)
        CURRENT_INSTALL_READY="0"
        ;;
    esac
  fi
  log "current_install_present=$CURRENT_INSTALL_PRESENT current_install_ready=$CURRENT_INSTALL_READY"
  if [ "$ACTIVATE_RECOVERY" = "1" ]; then
    [ "$CURRENT_INSTALL_PRESENT" = "1" ] \
      || fail "current_install_missing_for_recovery_activation"
    [ "$CURRENT_INSTALL_READY" = "0" ] \
      || fail "current_install_still_ready"
  fi
}

resolve_user_home() {
  local user_name="$1"
  local home_path=""
  if command -v getent >/dev/null 2>&1; then
    home_path="$(getent passwd "$user_name" 2>/dev/null | awk -F: 'NR == 1 { print $6 }' || true)"
  fi
  if [ -z "$home_path" ] && command -v dscl >/dev/null 2>&1; then
    home_path="$(dscl . -read "/Users/$user_name" NFSHomeDirectory 2>/dev/null | awk 'NR == 1 { print $2 }' || true)"
  fi
  if [ -z "$home_path" ] && [ "$user_name" = "$(id -un)" ]; then
    home_path="${HOME:-}"
  fi
  [ -n "$home_path" ] || fail "target_home_not_found user=$user_name"
  printf '%s\n' "$home_path"
}

path_owner_uid() {
  if stat -c '%u' "$1" >/dev/null 2>&1; then
    stat -c '%u' "$1"
  else
    stat -f '%u' "$1"
  fi
}

nearest_existing_path() {
  local candidate="$1"
  while [ ! -e "$candidate" ]; do
    [ "$candidate" != "/" ] || break
    candidate="$(dirname "$candidate")"
  done
  printf '%s\n' "$candidate"
}

target_can_write() {
  local path="$1"
  if [ "$CURRENT_UID" = "$TARGET_UID" ]; then
    [ -w "$path" ]
    return
  fi
  if command -v runuser >/dev/null 2>&1; then
    runuser -u "$TARGET_USER" -- test -w "$path"
    return
  fi
  if command -v sudo >/dev/null 2>&1; then
    sudo -n -u "$TARGET_USER" test -w "$path"
    return
  fi
  return 1
}

validate_target_path() {
  local label="$1"
  local path="$2"
  local existing owner_uid
  case "$path" in
    /*) ;;
    *) fail "target_path_must_be_absolute name=$label" ;;
  esac
  existing="$(nearest_existing_path "$path")"
  [ -d "$existing" ] || fail "target_path_parent_not_directory name=$label"
  owner_uid="$(path_owner_uid "$existing")" || fail "target_path_owner_unreadable name=$label"
  [ "$owner_uid" = "$TARGET_UID" ] || fail "target_uid_mismatch name=$label expected=$TARGET_UID actual=$owner_uid"
  target_can_write "$existing" || fail "target_path_not_writable name=$label"
}

resolve_installation_principal() {
  CURRENT_UID="$(id -u)"
  CURRENT_USER="$(id -un)"
  ADMIN_CONTEXT="0"
  if [ "$CURRENT_UID" = "0" ] || [ -n "${SUDO_USER:-}" ] || [ -n "${SUDO_UID:-}" ]; then
    ADMIN_CONTEXT="1"
  fi

  if [ -z "$TARGET_USER_ARG" ] && [ "$ADMIN_CONTEXT" = "1" ]; then
    fail "target_user_required_for_admin_install"
  fi
  if [ "$ADMIN_CONTEXT" = "1" ] && {
    [ -z "$TARGET_UID_ARG" ] || [ -z "$TARGET_HOME_ARG" ] || [ -z "$WPS_JSADDONS_DIR_ARG" ];
  }; then
    fail "admin_target_identity_required options=--target-user,--target-uid,--target-home,--wps-jsaddons-dir"
  fi

  TARGET_USER="${TARGET_USER_ARG:-$CURRENT_USER}"
  TARGET_UID="$(id -u "$TARGET_USER" 2>/dev/null)" || fail "target_user_not_found user=$TARGET_USER"
  [ "$TARGET_UID" != "0" ] || fail "root_target_user_rejected"
  if [ -n "$TARGET_UID_ARG" ] && [ "$TARGET_UID_ARG" != "$TARGET_UID" ]; then
    fail "target_uid_mismatch expected=$TARGET_UID_ARG actual=$TARGET_UID"
  fi
  if [ "$CURRENT_UID" != "0" ] && [ "$TARGET_UID" != "$CURRENT_UID" ]; then
    fail "target_user_uid_mismatch current=$CURRENT_UID target=$TARGET_UID"
  fi

  TARGET_HOME="$(resolve_user_home "$TARGET_USER")"
  TARGET_HOME="${TARGET_HOME%/}"
  if [ -n "$TARGET_HOME_ARG" ] && [ "${TARGET_HOME_ARG%/}" != "$TARGET_HOME" ]; then
    fail "target_home_mismatch expected=${TARGET_HOME_ARG%/} actual=$TARGET_HOME"
  fi
  [ -d "$TARGET_HOME" ] || fail "target_home_missing user=$TARGET_USER"
  [ "$(path_owner_uid "$TARGET_HOME")" = "$TARGET_UID" ] || fail "target_home_uid_mismatch user=$TARGET_USER"

  if [ -n "$WPS_JSADDONS_DIR_ARG" ]; then
    if [ -n "${WPS_JSADDONS_DIR:-}" ] && [ "$WPS_JSADDONS_DIR" != "$WPS_JSADDONS_DIR_ARG" ]; then
      fail "wps_jsaddons_dir_mismatch"
    fi
    WPS_JSADDONS_DIR="$WPS_JSADDONS_DIR_ARG"
  else
    WPS_JSADDONS_DIR="${WPS_JSADDONS_DIR:-$TARGET_HOME/.local/share/Kingsoft/wps/jsaddons}"
  fi
  INSTALL_ROOT="${AI_WPS_INSTALL_ROOT:-$TARGET_HOME/ai-wps-phase1}"
  validate_target_path "wps_jsaddons_dir" "$WPS_JSADDONS_DIR"
  validate_target_path "install_root" "$INSTALL_ROOT"
}

resolve_python_binary() {
  local resolved_python
  resolved_python="$(command -v "$PYTHON_BIN" 2>/dev/null)" || fail "python_not_found value=$PYTHON_BIN"
  [ -x "$resolved_python" ] || fail "python_not_executable path=$resolved_python"
  PYTHON_BIN="$resolved_python"
}

ensure_wps_processes_stopped() {
  local process_list process_name
  process_list="$(ps -u "$TARGET_UID" -o comm= 2>/dev/null)" || fail "wps_process_check_failed target_uid=$TARGET_UID"
  while IFS= read -r process_name; do
    process_name="$(printf '%s' "$process_name" | awk '{$1=$1; print}')"
    process_name="${process_name##*/}"
    process_name="$(printf '%s' "$process_name" | tr '[:upper:]' '[:lower:]')"
    case "$process_name" in
      wps|wps.bin|et|et.bin|wpp|wpp.bin)
        fail "wps_process_running process=$process_name target_uid=$TARGET_UID"
        ;;
    esac
  done <<< "$process_list"
}

adapter_port_is_listening() {
  if command -v lsof >/dev/null 2>&1; then
    [ -n "$(lsof -ti TCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true)" ]
    return
  fi
  if command -v ss >/dev/null 2>&1; then
    ss -ltn "sport = :$PORT" 2>/dev/null | grep -q LISTEN
    return
  fi
  if command -v fuser >/dev/null 2>&1; then
    fuser "${PORT}/tcp" >/dev/null 2>&1
    return
  fi
  curl -fsS "http://127.0.0.1:${PORT}/health/live" >/dev/null 2>&1
}

stop_adapter_for_state_transition() {
  if command -v systemctl >/dev/null 2>&1 && [ -f "$SYSTEMD_SERVICE_FILE" ]; then
    SYSTEMD_SERVICE_PRESENT="1"
    if [ "$(id -u)" != "0" ] \
      && [ "${AI_WPS_SYSTEMD_MANAGED_BY_PARENT:-0}" != "1" ]; then
      fail "adapter_service_update_requires_admin service=$SYSTEMD_SERVICE_NAME"
    fi
  fi
  if [ "$SYSTEMD_SERVICE_PRESENT" = "1" ] \
    && systemctl is-active --quiet "$SYSTEMD_SERVICE_NAME"; then
    [ "$(id -u)" = "0" ] || fail "adapter_service_stop_requires_admin service=$SYSTEMD_SERVICE_NAME"
    SYSTEMD_WAS_ACTIVE="1"
    systemctl stop "$SYSTEMD_SERVICE_NAME" \
      || fail "adapter_service_stop_failed service=$SYSTEMD_SERVICE_NAME"
  fi
  if [ -f "$ADAPTER_TARGET/scripts/stop_adapter.sh" ]; then
    AI_WPS_STATE_DIR="$STATE_DIR" \
      AI_WPS_BACKUP_DIR="$BACKUP_DIR" \
      AI_WPS_VAR_DIR="$VAR_DIR" \
      bash "$ADAPTER_TARGET/scripts/stop_adapter.sh" "$PORT" \
      || fail "adapter_stop_failed"
  fi
  adapter_port_is_listening && fail "adapter_port_still_listening port=$PORT"
  log "adapter_state_transition_lock=stopped port=$PORT"
}

install_current_systemd_service() {
  local temporary_unit
  [ "$SYSTEMD_SERVICE_PRESENT" = "1" ] || return 0
  [ "$(id -u)" = "0" ] || {
    log "adapter_service_update_requires_admin service=$SYSTEMD_SERVICE_NAME"
    return 1
  }
  [ -f "$CURRENT_LINK/scripts/systemd_unit.sh" ] \
    || { log "adapter_systemd_renderer_missing"; return 1; }
  source "$CURRENT_LINK/scripts/systemd_unit.sh"
  temporary_unit="${SYSTEMD_SERVICE_FILE}.ai-wps-$$.tmp"
  render_adapter_systemd_unit \
    "$temporary_unit" \
    "$TARGET_USER" \
    "$CURRENT_LINK" \
    "$PYTHON_BIN" \
    "$PORT" \
    "$VAR_DIR/run/adapter.pid" \
    "$STATE_DIR" \
    "$BACKUP_DIR" \
    "$VAR_DIR" \
    || { log "adapter_systemd_render_failed"; rm -f "$temporary_unit"; return 1; }
  chmod 644 "$temporary_unit"
  mv -f "$temporary_unit" "$SYSTEMD_SERVICE_FILE" \
    || { log "adapter_systemd_replace_failed"; return 1; }
  systemctl daemon-reload \
    || { log "adapter_systemd_reload_failed"; return 1; }
  AI_WPS_STATE_DIR="$STATE_DIR" \
    AI_WPS_BACKUP_DIR="$BACKUP_DIR" \
    AI_WPS_VAR_DIR="$VAR_DIR" \
    bash "$CURRENT_LINK/scripts/stop_adapter.sh" "$PORT" \
    || { log "adapter_direct_stop_before_systemd_failed"; return 1; }
  systemctl start "$SYSTEMD_SERVICE_NAME" \
    || { log "adapter_systemd_start_failed service=$SYSTEMD_SERVICE_NAME"; return 1; }
  log "adapter_systemd_generation=current service=$SYSTEMD_SERVICE_NAME"
}

write_systemd_handoff() {
  local previous_was_active="${AI_WPS_SYSTEMD_WAS_ACTIVE:-$SYSTEMD_WAS_ACTIVE}"
  [ -n "$SYSTEMD_HANDOFF_FILE" ] \
    || { log "adapter_systemd_handoff_path_missing"; return 1; }
  case "$previous_was_active" in
    0|1) ;;
    *) log "adapter_systemd_previous_activity_invalid"; return 1 ;;
  esac
  "$PYTHON_BIN" - "$SYSTEMD_HANDOFF_FILE" "$TRANSACTION_LOG" "$SYSTEMD_UNIT_BACKUP" "$previous_was_active" <<'PY'
import json
import os
from pathlib import Path
import sys
import uuid

target = Path(sys.argv[1])
target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
temporary = target.with_name(".{0}.{1}.tmp".format(target.name, uuid.uuid4().hex))
descriptor = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
    json.dump(
        {
            "transactionLog": sys.argv[2],
            "unitBackup": sys.argv[3],
            "wasActive": sys.argv[4] == "1",
        },
        handle,
        ensure_ascii=False,
        sort_keys=True,
    )
    handle.write("\n")
    handle.flush()
    os.fsync(handle.fileno())
os.replace(str(temporary), str(target))
directory = os.open(str(target.parent), os.O_RDONLY)
try:
    os.fsync(directory)
finally:
    os.close(directory)
PY
}

recover_systemd_handoff() {
  local previous_was_active transaction_log transaction_status
  [ "$(id -u)" = "0" ] || return 0
  [ -n "$SYSTEMD_HANDOFF_FILE" ] && [ -f "$SYSTEMD_HANDOFF_FILE" ] || return 0
  transaction_log="$(
    "$PYTHON_BIN" -c \
      'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8")).get("transactionLog", ""))' \
      "$SYSTEMD_HANDOFF_FILE" 2>/dev/null || true
  )"
  transaction_status="$(
    "$PYTHON_BIN" -c \
      'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8")).get("status", ""))' \
      "$transaction_log" 2>/dev/null || true
  )"
  if [ "$transaction_status" = "committed" ] \
    || [ "$transaction_status" = "recovery_activated" ]; then
    rm -f "$SYSTEMD_UNIT_BACKUP" "$SYSTEMD_HANDOFF_FILE"
    return 0
  fi
  [ -n "$transaction_log" ] && [ -f "$transaction_log" ] \
    || fail "adapter_systemd_recovery_transaction_missing"
  previous_was_active="$(
    "$PYTHON_BIN" -c \
      'import json,sys; value=json.load(open(sys.argv[1], encoding="utf-8")).get("wasActive"); print("1" if value is True else "0" if value is False else "")' \
      "$SYSTEMD_HANDOFF_FILE" 2>/dev/null || true
  )"
  case "$previous_was_active" in
    0|1) ;;
    *) fail "adapter_systemd_recovery_activity_missing" ;;
  esac
  stop_candidate_adapter_for_systemd_compensation \
    || fail "adapter_systemd_recovery_candidate_stop_failed"
  "$PYTHON_BIN" -s "$TRANSACTION_TOOL" rollback "$transaction_log" \
    || fail "adapter_systemd_recovery_transaction_rollback_failed"
  if [ -f "$SYSTEMD_UNIT_BACKUP" ]; then
    mv -f "$SYSTEMD_UNIT_BACKUP" "$SYSTEMD_SERVICE_FILE"
    log "adapter_systemd_unit=recovered_previous"
  fi
  systemctl daemon-reload || fail "adapter_systemd_recovery_reload_failed"
  if [ "$previous_was_active" = "1" ]; then
    systemctl start "$SYSTEMD_SERVICE_NAME" \
      || fail "adapter_systemd_recovery_restart_failed"
  fi
  SYSTEMD_WAS_ACTIVE="$previous_was_active"
  rm -f "$SYSTEMD_HANDOFF_FILE"
  log "adapter_systemd_generation=recovered_previous wasActive=$previous_was_active"
}

stop_candidate_adapter_for_systemd_compensation() {
  systemctl stop "$SYSTEMD_SERVICE_NAME" >/dev/null 2>&1 || true
  if [ -f "$CURRENT_LINK/scripts/stop_adapter.sh" ]; then
    AI_WPS_STATE_DIR="$STATE_DIR" \
      AI_WPS_BACKUP_DIR="$BACKUP_DIR" \
      AI_WPS_VAR_DIR="$VAR_DIR" \
      bash "$CURRENT_LINK/scripts/stop_adapter.sh" "$PORT" \
      || return 1
  fi
}

compensate_systemd_release() {
  local transaction_log="$1"
  if ! stop_candidate_adapter_for_systemd_compensation; then
    log "candidate_adapter_stop_during_rollback_failed=$SYSTEMD_SERVICE_NAME"
    log "adapter_systemd_compensation=pending_retry"
    return 1
  fi
  if ! "$PYTHON_BIN" -s "$TRANSACTION_TOOL" rollback "$transaction_log"; then
    log "release_transaction_rollback_failed=$transaction_log"
    log "adapter_systemd_compensation=pending_retry"
    return 1
  fi
  if [ -f "$SYSTEMD_UNIT_BACKUP" ]; then
    mv -f "$SYSTEMD_UNIT_BACKUP" "$SYSTEMD_SERVICE_FILE" \
      || { log "previous_adapter_systemd_restore_failed=$SYSTEMD_SERVICE_NAME"; return 1; }
  fi
  systemctl daemon-reload \
    || { log "previous_adapter_systemd_reload_failed=$SYSTEMD_SERVICE_NAME"; return 1; }
  if [ "$SYSTEMD_WAS_ACTIVE" = "1" ]; then
    systemctl start "$SYSTEMD_SERVICE_NAME" \
      || { log "previous_adapter_service_restart_failed=$SYSTEMD_SERVICE_NAME"; return 1; }
  fi
  rm -f "$SYSTEMD_HANDOFF_FILE"
  log "adapter_systemd_compensation=completed"
}

complete_systemd_release() {
  local transaction_log transaction_status
  transaction_log="$(
    "$PYTHON_BIN" -c \
      'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8")).get("transactionLog", ""))' \
      "$SYSTEMD_HANDOFF_FILE" 2>/dev/null || true
  )"
  [ -n "$transaction_log" ] && [ -f "$transaction_log" ] \
    || { log "adapter_systemd_handoff_invalid"; return 1; }
  [ ! -e "$SYSTEMD_UNIT_BACKUP" ] \
    || { log "adapter_systemd_backup_exists"; return 1; }
  cp -p "$SYSTEMD_SERVICE_FILE" "$SYSTEMD_UNIT_BACKUP" \
    || { log "adapter_systemd_backup_failed"; return 1; }
  if ! install_current_systemd_service; then
    compensate_systemd_release "$transaction_log"
    return 1
  fi
  if ! "$PYTHON_BIN" -s "$TRANSACTION_TOOL" commit "$transaction_log"; then
    compensate_systemd_release "$transaction_log"
    return 1
  fi
  transaction_status="$(
    "$PYTHON_BIN" -c \
      'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8")).get("status", ""))' \
      "$transaction_log" 2>/dev/null || true
  )"
  rm -f "$SYSTEMD_UNIT_BACKUP" "$SYSTEMD_HANDOFF_FILE"
  if [ "$transaction_status" = "recovery_activated" ]; then
    log "recovery_mode_activated=true systemd=true"
  else
    log "release_generation=committed_with_systemd"
  fi
}

reexec_as_target_if_needed() {
  local child_status
  local reexec_arguments=(
    --target-user "$TARGET_USER"
    --target-uid "$TARGET_UID"
    --target-home "$TARGET_HOME"
    --wps-jsaddons-dir "$WPS_JSADDONS_DIR"
  )
  if [ "$ACTIVATE_RECOVERY" = "1" ]; then
    reexec_arguments+=(--activate-recovery)
  fi
  [ "$CURRENT_UID" = "0" ] || return 0
  if command -v runuser >/dev/null 2>&1; then
    child_status="0"
    runuser -u "$TARGET_USER" -- env \
      HOME="$TARGET_HOME" \
      AI_WPS_INSTALL_ROOT="$INSTALL_ROOT" \
      WPS_JSADDONS_DIR="$WPS_JSADDONS_DIR" \
      AI_WPS_STATE_DIR="$STATE_DIR" \
      AI_WPS_BACKUP_DIR="$BACKUP_DIR" \
      AI_WPS_VAR_DIR="$VAR_DIR" \
      PYTHON_BIN="$PYTHON_BIN" \
      PORT="$PORT" \
      AI_WPS_CANDIDATE_PORT="${AI_WPS_CANDIDATE_PORT:-}" \
      AI_WPS_SYSTEMD_MANAGED_BY_PARENT="$SYSTEMD_SERVICE_PRESENT" \
      AI_WPS_DEFER_RELEASE_COMMIT="$SYSTEMD_SERVICE_PRESENT" \
      AI_WPS_SYSTEMD_HANDOFF_FILE="$SYSTEMD_HANDOFF_FILE" \
      AI_WPS_SYSTEMD_UNIT_BACKUP="$SYSTEMD_UNIT_BACKUP" \
      AI_WPS_SYSTEMD_WAS_ACTIVE="$SYSTEMD_WAS_ACTIVE" \
      bash "$DELIVERY_ROOT/installer/install_phase1.sh" \
        "${reexec_arguments[@]}" \
      || child_status="$?"
    if [ "$child_status" = "0" ] && [ "$SYSTEMD_SERVICE_PRESENT" = "1" ]; then
      if ! complete_systemd_release; then
        child_status="1"
      fi
    elif [ "$SYSTEMD_WAS_ACTIVE" = "1" ]; then
      systemctl start "$SYSTEMD_SERVICE_NAME" \
        || log "previous_adapter_service_restart_failed=$SYSTEMD_SERVICE_NAME"
    fi
    exit "$child_status"
  fi
  fail "target_user_execution_tool_missing"
}

copy_dir() {
  local source_dir="$1"
  local target_dir="$2"
  rm -rf "$target_dir"
  mkdir -p "$(dirname "$target_dir")"
  cp -R "$source_dir" "$target_dir"
}

json_field() {
  local field="$1"
  "$PYTHON_BIN" -c \
    'import json,sys; value=json.load(sys.stdin); print(value.get(sys.argv[1], ""))' \
    "$field"
}

resolve_active_adapter() {
  if [ -e "$CURRENT_LINK" ] || [ -L "$CURRENT_LINK" ]; then
    ADAPTER_TARGET="$CURRENT_LINK"
  else
    ADAPTER_TARGET="$LEGACY_ADAPTER_TARGET"
  fi
}

recover_incomplete_transactions() {
  local transaction_log status
  mkdir -p "$VAR_DIR/transactions"
  chmod 700 "$VAR_DIR" "$VAR_DIR/transactions"
  for transaction_log in "$VAR_DIR"/transactions/*.json; do
    [ -f "$transaction_log" ] || continue
    status="$("$PYTHON_BIN" -c \
      'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8")).get("status", ""))' \
      "$transaction_log" 2>/dev/null || true)"
    case "$status" in
      prepared|switching|awaiting_finalization|ready_to_commit|verification_failed|rolling_back)
        "$PYTHON_BIN" -s "$TRANSACTION_TOOL" recover "$transaction_log" \
          || fail "release_transaction_recovery_failed path=$transaction_log"
        log "release_transaction_recovered=$transaction_log"
        ;;
    esac
  done
}

initialize_writing_policy_database() {
  local adapter_root="${1:-$ADAPTER_TARGET}"
  local database_root="${2:-${STATE_DIR:-$ADAPTER_TARGET/run}}"
  local database_path="$database_root/writing_policies.db"
  local adapter_pythonpath="$adapter_root/adapter_service"

  if [ -d "$adapter_root/python-runtime" ]; then
    adapter_pythonpath="$adapter_root/python-runtime:$adapter_pythonpath"
  fi

  if [ -e "$database_path" ]; then
    log "writing_policy_database=reused path=$database_path"
    return 0
  fi

  mkdir -p "$database_root"
  chmod 700 "$database_root"
  if AI_WPS_WRITING_POLICY_DB="$database_path" \
    PYTHONNOUSERSITE=1 \
    PYTHONPATH="$adapter_pythonpath" \
    "$PYTHON_BIN" -s -c \
      "from app.services.writing_policy.service import get_writing_policy_service; get_writing_policy_service().store.summary()"; then
    chmod 600 "$database_path"
    log "writing_policy_database=initialized path=$database_path"
    return 0
  fi

  fail "writing_policy_database_initialization_failed"
}

runtime_state_exists() {
  [ -f "$STATE_DIR/adapter.json" ] \
    || [ -f "$STATE_DIR/provider_api_key" ] \
    || [ -d "$STATE_DIR/provider_api_keys" ] \
    || [ -f "$STATE_DIR/writing_policies.db" ]
}

legacy_runtime_state_exists() {
  [ -f "$ADAPTER_TARGET/config/adapter.json" ] \
    || [ -f "$ADAPTER_TARGET/run/provider_api_key" ] \
    || [ -d "$ADAPTER_TARGET/run/provider_api_keys" ] \
    || [ -f "$ADAPTER_TARGET/run/writing_policies.db" ]
}

prepare_runtime_state() {
  local result status copy_verified
  local candidate_state_tool="$CANDIDATE_TARGET/adapter_service/tools/runtime_state.py"
  local candidate_pythonpath="$CANDIDATE_TARGET/python-runtime:$CANDIDATE_TARGET/adapter_service"

  [ -f "$candidate_state_tool" ] || fail "runtime_state_tool_missing"
  mkdir -p "$(dirname "$STATE_DIR")" "$BACKUP_DIR" "$VAR_DIR/logs" "$VAR_DIR/run" "$VAR_DIR/transactions"
  chmod 700 "$BACKUP_DIR" "$VAR_DIR" \
    "$VAR_DIR/logs" "$VAR_DIR/run" "$VAR_DIR/transactions"

  if runtime_state_exists; then
    result="$(
      PYTHONNOUSERSITE=1 PYTHONPATH="$candidate_pythonpath" \
        "$PYTHON_BIN" -s "$candidate_state_tool" snapshot \
        --state-dir "$STATE_DIR" \
        --backup-dir "$BACKUP_DIR" \
        --release-version "$PREVIOUS_RELEASE_VERSION" \
        --reason pre_install
    )" || fail "runtime_state_snapshot_failed"
    PREVIOUS_SNAPSHOT_ID="$(printf '%s' "$result" | json_field snapshotId)"
    [ -n "$PREVIOUS_SNAPSHOT_ID" ] || fail "runtime_state_snapshot_id_missing"
    status="$(printf '%s' "$result" | json_field status)"
    copy_verified="$(printf '%s' "$result" | json_field copyVerified)"
    [ "$copy_verified" = "True" ] || [ "$copy_verified" = "true" ] \
      || fail "runtime_state_snapshot_copy_not_verified"
    RUNTIME_BACKUP_VERIFIED="1"
    log "runtime_state_snapshot_reason=pre_install"
    case "$status" in
      recovery)
        log "runtime_state_snapshot_status=recovery"
        ;;
      degraded)
        log "runtime_state_snapshot_status=degraded"
        ;;
      ready)
        log "runtime_state_snapshot_status=ready"
        ;;
      *) fail "runtime_state_snapshot_status=invalid value=$status" ;;
    esac
    copy_dir "$BACKUP_DIR/$PREVIOUS_SNAPSHOT_ID/state" "$CANDIDATE_STATE"
    chmod 700 "$CANDIDATE_STATE"
    return 0
  fi

  if legacy_runtime_state_exists; then
    result="$(
      PYTHONNOUSERSITE=1 PYTHONPATH="$candidate_pythonpath" \
        "$PYTHON_BIN" -s "$candidate_state_tool" migrate \
        --state-dir "$CANDIDATE_STATE" \
        --backup-dir "$BACKUP_DIR" \
        --release-version "$PREVIOUS_RELEASE_VERSION" \
        --legacy-root "$ADAPTER_TARGET"
    )" || fail "runtime_state_migration_status=recovery"
    PREVIOUS_SNAPSHOT_ID="$(printf '%s' "$result" | json_field snapshotId)"
    [ -n "$PREVIOUS_SNAPSHOT_ID" ] || fail "runtime_state_migration_snapshot_id_missing"
    status="$(printf '%s' "$result" | json_field status)"
    case "$status" in
      degraded) log "runtime_state_migration_status=degraded" ;;
      ready) log "runtime_state_migration_status=ready" ;;
      *) fail "runtime_state_migration_status=invalid value=$status" ;;
    esac
    return 0
  fi

  mkdir -p "$CANDIDATE_STATE"
  chmod 700 "$CANDIDATE_STATE"
  log "runtime_state_status=fresh"
}

create_candidate_state_snapshot() {
  local result status copy_verified
  local candidate_state_tool="$CANDIDATE_TARGET/adapter_service/tools/runtime_state.py"
  local candidate_pythonpath="$CANDIDATE_TARGET/python-runtime:$CANDIDATE_TARGET/adapter_service"

  result="$(
    PYTHONNOUSERSITE=1 PYTHONPATH="$candidate_pythonpath" \
      "$PYTHON_BIN" -s "$candidate_state_tool" snapshot \
      --state-dir "$CANDIDATE_STATE" \
      --backup-dir "$BACKUP_DIR" \
      --release-version "$RELEASE_VERSION" \
      --reason candidate_release
  )" || fail "candidate_state_snapshot_failed"
  CANDIDATE_SNAPSHOT_ID="$(printf '%s' "$result" | json_field snapshotId)"
  [ -n "$CANDIDATE_SNAPSHOT_ID" ] || fail "candidate_state_snapshot_id_missing"
  status="$(printf '%s' "$result" | json_field status)"
  copy_verified="$(printf '%s' "$result" | json_field copyVerified)"
  [ "$copy_verified" = "True" ] || [ "$copy_verified" = "true" ] \
    || fail "candidate_state_snapshot_copy_not_verified"
  case "$status" in
    recovery) log "candidate_state_snapshot_status=recovery" ;;
    degraded) log "candidate_state_snapshot_status=degraded" ;;
    ready) log "candidate_state_snapshot_status=ready" ;;
    *) fail "candidate_state_snapshot_status=invalid value=$status" ;;
  esac
}

enable_exec_permissions() {
  if [ -d "$ADAPTER_TARGET/scripts" ]; then
    find "$ADAPTER_TARGET/scripts" -type f -name '*.sh' -exec chmod +x {} \;
  fi
  if [ -d "$ADAPTER_TARGET/adapter_service" ]; then
    find "$ADAPTER_TARGET/adapter_service" -type f -name '*.py' -exec chmod +x {} \;
  fi
}

prepare_candidate_adapter() {
  [ -d "$ADAPTER_SOURCE" ] || fail "adapter_source_missing"
  [ -x "$PYTHON_BIN" ] || fail "python_not_executable path=$PYTHON_BIN"
  [ -f "$DELIVERY_ROOT/installer/install_private_runtime.sh" ] || fail "private_runtime_installer_missing"
  [ -f "$DELIVERY_ROOT/installer/preflight_candidate.sh" ] || fail "candidate_preflight_script_missing"
  [ -f "$RELEASE_MANIFEST_SOURCE" ] || fail "release_manifest_missing"
  [ -f "$TRANSACTION_TOOL" ] || fail "release_transaction_tool_missing"

  mkdir -p "$RELEASES_DIR"
  copy_dir "$ADAPTER_SOURCE" "$CANDIDATE_TARGET"
  cp "$RELEASE_MANIFEST_SOURCE" "$CANDIDATE_TARGET/release-manifest.json"
  "$PYTHON_BIN" - "$CANDIDATE_TARGET/release-manifest.json" "$RELEASE_VERSION" <<'PY' \
    || fail "candidate_release_manifest_invalid"
import json
from pathlib import Path
import sys

manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
expected = sys.argv[2]
policy = manifest.get("releaseGenerationPolicy", {})
assert manifest.get("schemaVersion") == 1
assert manifest.get("version") == expected
assert manifest.get("adapter", {}).get("version") == expected
assert policy.get("switchStrategy") == "durable-compensating-rename"
assert policy.get("currentPointer") == "current"
assert policy.get("components") == [
    "adapter_release",
    "word_plugin",
    "excel_plugin",
    "ppt_plugin",
    "publish_manifest",
    "runtime_state_snapshot",
    "current_pointer",
]
PY
  bash "$DELIVERY_ROOT/installer/install_private_runtime.sh" \
    "$PYTHON_BIN" \
    "$RUNTIME_DEPS_DIR" \
    "$PIP_BOOTSTRAP_DIR" \
    "$CANDIDATE_TARGET/python-runtime"
  : > "$CANDIDATE_TARGET/.release-private-runtime-required"
  find "$CANDIDATE_TARGET" -type f -name '*.sh' -exec chmod 755 {} \;
  find "$CANDIDATE_TARGET/adapter_service" -type f -name '*.py' -exec chmod 755 {} \;
  log "candidate_adapter=prepared path=$CANDIDATE_TARGET"
}

run_candidate_preflight() {
  local result
  result="$(
    AI_WPS_PREFLIGHT_STATE_SOURCE="$BACKUP_DIR/$CANDIDATE_SNAPSHOT_ID/state" \
      bash "$DELIVERY_ROOT/installer/preflight_candidate.sh" \
      "$PYTHON_BIN" \
      "$CANDIDATE_TARGET" \
      "$CANDIDATE_TARGET/python-runtime" \
      "$CANDIDATE_PORT" \
      "$RELEASE_VERSION" \
      "$PREFLIGHT_ROOT"
  )" || {
    log "$result"
    fail "candidate_preflight_failed"
  }
  log "$result"
  CANDIDATE_HEALTH_STATUS="$(
    printf '%s\n' "$result" \
      | sed -n 's/^candidate_preflight=\([^ ]*\).*/\1/p' \
      | tail -n 1
  )"
  case "$CANDIDATE_HEALTH_STATUS" in
    ready|degraded|recovery) ;;
    *) fail "candidate_preflight_status_missing" ;;
  esac
  CANDIDATE_RECOVERY_SUMMARY="$(
    printf '%s\n' "$result" \
      | sed -n 's/^candidate_recovery_fault_summary=\(.*\)$/\1/p' \
      | tail -n 1
  )"
  if [ "$CANDIDATE_HEALTH_STATUS" = "recovery" ]; then
    [ -n "$CANDIDATE_RECOVERY_SUMMARY" ] \
      || fail "candidate_recovery_summary_missing"
  fi
}

enforce_recovery_activation_gate() {
  if [ "$CANDIDATE_HEALTH_STATUS" = "recovery" ]; then
    [ "$CURRENT_INSTALL_PRESENT" = "1" ] \
      || fail "current_install_missing_for_recovery_activation"
    [ "$RUNTIME_BACKUP_VERIFIED" = "1" ] \
      || fail "recovery_activation_backup_not_verified"
    [ -n "$PREVIOUS_SNAPSHOT_ID" ] \
      || fail "recovery_activation_backup_id_missing"
    if [ "$ACTIVATE_RECOVERY" != "1" ]; then
      PRESERVE_RECOVERY_CANDIDATE="1"
      log "candidate_recovery_requires_explicit_activation=true"
      log "candidate_recovery_path=$CANDIDATE_TARGET"
      log "candidate_recovery_state_path=$CANDIDATE_STATE"
      log "verified_backup_id=$PREVIOUS_SNAPSHOT_ID"
      log "recovery_command=bash installer/install_phase1.sh --activate-recovery"
      exit 2
    fi
    [ "$CURRENT_INSTALL_READY" = "0" ] \
      || fail "current_install_still_ready"
    log "recovery_activation_gate=accepted backup=$PREVIOUS_SNAPSHOT_ID"
    return 0
  fi
  [ "$ACTIVATE_RECOVERY" != "1" ] \
    || fail "candidate_not_in_recovery"
}

stage_wps_plugins() {
  [ -d "$WORD_PLUGIN_SOURCE" ] || fail "word_plugin_source_missing"
  [ -d "$EXCEL_PLUGIN_SOURCE" ] || fail "excel_plugin_source_missing"
  [ -d "$PPT_PLUGIN_SOURCE" ] || fail "ppt_plugin_source_missing"
  [ -f "$PUBLISH_SOURCE" ] || fail "publish_xml_missing"

  mkdir -p "$WPS_JSADDONS_DIR"
  copy_dir "$WORD_PLUGIN_SOURCE" "$WORD_PLUGIN_CANDIDATE"
  copy_dir "$EXCEL_PLUGIN_SOURCE" "$EXCEL_PLUGIN_CANDIDATE"
  copy_dir "$PPT_PLUGIN_SOURCE" "$PPT_PLUGIN_CANDIDATE"

  if [ -f "$WPS_JSADDONS_DIR/publish.xml" ]; then
    {
      printf '%s\n' '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
      printf '%s\n' '<jsplugins>'
      printf '%s\n' '  <jsplugin name="wps-ai-assistant" url="file://" type="wps" enable="enable_dev" version="1.0.0"/>'
      printf '%s\n' '  <jsplugin name="wps-ai-assistant-et" url="file://" type="et" enable="enable_dev" version="1.0.0"/>'
      printf '%s\n' '  <jsplugin name="wps-ai-assistant-wpp" url="file://" type="wpp" enable="enable_dev" version="1.0.0"/>'
      grep '<jsplugin ' "$WPS_JSADDONS_DIR/publish.xml" \
        | grep -v 'name="wps-ai-assistant"' \
        | grep -v 'name="wps-ai-assistant-et"' \
        | grep -v 'name="wps-ai-assistant-wpp"' || true
      printf '%s\n' '</jsplugins>'
    } > "$PUBLISH_CANDIDATE"
  else
    cp "$PUBLISH_SOURCE" "$PUBLISH_CANDIDATE"
  fi

  "$PYTHON_BIN" - "$RELEASE_MANIFEST_SOURCE" "$RELEASE_VERSION" \
    "$WORD_PLUGIN_CANDIDATE" "$EXCEL_PLUGIN_CANDIDATE" \
    "$PPT_PLUGIN_CANDIDATE" "$PUBLISH_CANDIDATE" <<'PY' \
    || fail "candidate_plugin_generation_invalid"
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
release_version = sys.argv[2]
expected_hosts = [
    ("Word", "wps-ai-assistant_1.0.0", "wps", "wps-ai-assistant"),
    ("Excel", "wps-ai-assistant-et_1.0.0", "et", "wps-ai-assistant-et"),
    ("PPT", "wps-ai-assistant-wpp_1.0.0", "wpp", "wps-ai-assistant-wpp"),
]
actual_hosts = [
    (item.get("name"), item.get("plugin"), item.get("ribbonType"))
    for item in manifest.get("hosts", [])
]
assert actual_hosts == [item[:3] for item in expected_hosts]
for plugin_root, expected_host in zip(map(Path, sys.argv[3:6]), expected_hosts):
    plugin = json.loads(
        (plugin_root / "manifest.json").read_text(encoding="utf-8")
    )
    assert plugin.get("name") == expected_host[3]
    assert plugin.get("version") == release_version
publish = ET.parse(sys.argv[6]).getroot()
declared = {
    (item.get("name"), item.get("type"), item.get("version"))
    for item in publish.findall("jsplugin")
}
assert {
    (item[3], item[2], item[1].rsplit("_", 1)[1])
    for item in expected_hosts
}.issubset(declared)
PY

  log "candidate_plugins=staged transaction=$TRANSACTION_ID"
}

write_generation_manifest() {
  "$PYTHON_BIN" - "$CANDIDATE_TARGET/release-generation.json" \
    "$RELEASE_VERSION" "$CANDIDATE_SNAPSHOT_ID" "$RELEASE_MANIFEST_SOURCE" <<'PY'
import hashlib
import json
from pathlib import Path
import sys

target = Path(sys.argv[1])
release_manifest = Path(sys.argv[4])
payload = {
    "schemaVersion": 1,
    "releaseVersion": sys.argv[2],
    "candidateSnapshotId": sys.argv[3],
    "releaseManifestSha256": hashlib.sha256(release_manifest.read_bytes()).hexdigest(),
    "components": [
        "adapter_release",
        "word_plugin",
        "excel_plugin",
        "ppt_plugin",
        "publish_manifest",
        "runtime_state_snapshot",
        "current_pointer",
    ],
}
target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
  chmod 600 "$CANDIDATE_TARGET/release-generation.json"
}

prepare_release_transaction() {
  local transaction_result
  local transaction_arguments=(
    prepare
    --transaction-dir "$VAR_DIR/transactions"
    --transaction-id "$TRANSACTION_ID"
    --release-version "$RELEASE_VERSION"
    --backup-dir "$BACKUP_DIR"
    --candidate-snapshot-id "$CANDIDATE_SNAPSHOT_ID"
    --component adapter_release "$CANDIDATE_TARGET" "$RELEASE_TARGET"
    --component word_plugin "$WORD_PLUGIN_CANDIDATE" "$WPS_JSADDONS_DIR/$WORD_PLUGIN_NAME"
    --component excel_plugin "$EXCEL_PLUGIN_CANDIDATE" "$WPS_JSADDONS_DIR/$EXCEL_PLUGIN_NAME"
    --component ppt_plugin "$PPT_PLUGIN_CANDIDATE" "$WPS_JSADDONS_DIR/$PPT_PLUGIN_NAME"
    --component publish_manifest "$PUBLISH_CANDIDATE" "$WPS_JSADDONS_DIR/publish.xml"
    --component runtime_state_snapshot "$CANDIDATE_STATE" "$STATE_DIR"
    --component current_pointer "$CURRENT_CANDIDATE" "$CURRENT_LINK"
  )
  if [ "$ACTIVATE_RECOVERY" = "1" ]; then
    transaction_arguments=(prepare --recovery-activation "${transaction_arguments[@]:1}")
  fi
  if ! transaction_result="$(
    "$PYTHON_BIN" -s "$TRANSACTION_TOOL" "${transaction_arguments[@]}"
  )"; then
    log "$transaction_result"
    fail "release_transaction_prepare_failed"
  fi
  TRANSACTION_LOG="$(printf '%s' "$transaction_result" | json_field transactionLog)"
  [ -n "$TRANSACTION_LOG" ] || fail "release_transaction_log_missing"
  log "release_transaction=prepared path=$TRANSACTION_LOG"
}

switch_release_generation() {
  local fail_after="${AI_WPS_TRANSACTION_FAIL_AFTER:-}"
  local switch_arguments=(switch "$TRANSACTION_LOG")
  case "$fail_after" in
    '') ;;
    after_backup:adapter_release|after_switch:adapter_release|\
    after_backup:word_plugin|after_switch:word_plugin|\
    after_backup:excel_plugin|after_switch:excel_plugin|\
    after_backup:ppt_plugin|after_switch:ppt_plugin|\
    after_backup:publish_manifest|after_switch:publish_manifest|\
    after_backup:runtime_state_snapshot|after_switch:runtime_state_snapshot|\
    after_backup:current_pointer|after_switch:current_pointer)
      switch_arguments+=(--fail-after "$fail_after")
      ;;
    *) fail "transaction_failpoint_invalid value=$fail_after" ;;
  esac
  "$PYTHON_BIN" -s "$TRANSACTION_TOOL" "${switch_arguments[@]}" \
    || fail "release_generation_switch_failed"
  ADAPTER_TARGET="$CURRENT_LINK"
  log "release_generation=switched version=$RELEASE_VERSION"
}

finalize_release_generation() {
  if [ "${AI_WPS_DEFER_RELEASE_COMMIT:-0}" = "1" ]; then
    "$PYTHON_BIN" -s "$TRANSACTION_TOOL" finalize "$TRANSACTION_LOG" --defer-commit \
      || fail "release_generation_finalization_failed"
    if ! write_systemd_handoff; then
      "$PYTHON_BIN" -s "$TRANSACTION_TOOL" rollback "$TRANSACTION_LOG" \
        || log "release_transaction_rollback_failed=$TRANSACTION_LOG"
      fail "adapter_systemd_handoff_write_failed"
    fi
    if [ "$ACTIVATE_RECOVERY" = "1" ]; then
      log "recovery_mode_activation=ready_to_commit snapshot=$CANDIDATE_SNAPSHOT_ID"
    else
      log "release_generation=ready_to_commit version=$RELEASE_VERSION snapshot=$CANDIDATE_SNAPSHOT_ID"
    fi
  else
    "$PYTHON_BIN" -s "$TRANSACTION_TOOL" finalize "$TRANSACTION_LOG" \
      || fail "release_generation_finalization_failed"
    if [ "$ACTIVATE_RECOVERY" = "1" ]; then
      log "recovery_mode_activated=true snapshot=$CANDIDATE_SNAPSHOT_ID"
    else
      log "release_generation=committed version=$RELEASE_VERSION snapshot=$CANDIDATE_SNAPSHOT_ID"
    fi
  fi
}

start_and_check_adapter() {
  local health_result health_status
  log "adapter_start=uvicorn port=$PORT"
  AI_WPS_REQUIRE_PRIVATE_RUNTIME=1 \
    bash "$ADAPTER_TARGET/scripts/start_uvicorn_adapter.sh" "$PORT"
  if [ "$ACTIVATE_RECOVERY" = "1" ]; then
    health_status="0"
    health_result="$(
      bash "$ADAPTER_TARGET/scripts/check_health.sh" "$PORT"
    )" || health_status="$?"
    log "$health_result"
    case "$health_result" in
      *"adapter_health=reachable"*"adapter_business_status=recovery"*) ;;
      *) fail "activated_recovery_health_contract_invalid status=$health_status" ;;
    esac
  else
    bash "$ADAPTER_TARGET/scripts/check_health.sh" "$PORT"
  fi
}

restart_previous_adapter() {
  [ -f "$ADAPTER_TARGET/scripts/start_uvicorn_adapter.sh" ] || return 0
  if [ "$PREVIOUS_RELEASE_VERSION" = "legacy" ] && ! runtime_state_exists; then
    env -u AI_WPS_STATE_DIR -u AI_WPS_BACKUP_DIR -u AI_WPS_VAR_DIR \
      bash "$ADAPTER_TARGET/scripts/start_uvicorn_adapter.sh" "$PORT" \
      || log "previous_adapter_restart_failed=$ADAPTER_TARGET"
  else
    AI_WPS_REQUIRE_PRIVATE_RUNTIME=1 \
      bash "$ADAPTER_TARGET/scripts/start_uvicorn_adapter.sh" "$PORT" \
      || log "previous_adapter_restart_failed=$ADAPTER_TARGET"
  fi
}

parse_arguments "$@"
resolve_installation_principal
resolve_python_binary
case "$SYSTEMD_SERVICE_FILE" in
  /*) ;;
  *) fail "adapter_systemd_service_file_must_be_absolute" ;;
esac
STATE_DIR="${AI_WPS_STATE_DIR:-$INSTALL_ROOT/state}"
BACKUP_DIR="${AI_WPS_BACKUP_DIR:-$INSTALL_ROOT/backups}"
VAR_DIR="${AI_WPS_VAR_DIR:-$INSTALL_ROOT/var}"
SYSTEMD_HANDOFF_FILE="${AI_WPS_SYSTEMD_HANDOFF_FILE:-$VAR_DIR/run/systemd-release-handoff.json}"
RELEASES_DIR="$INSTALL_ROOT/releases"
RELEASE_TARGET="$RELEASES_DIR/$RELEASE_VERSION"
CURRENT_LINK="$INSTALL_ROOT/current"
LEGACY_ADAPTER_TARGET="$INSTALL_ROOT/adapter-start-kit"
resolve_active_adapter
validate_target_path "state_dir" "$STATE_DIR"
validate_target_path "backup_dir" "$BACKUP_DIR"
validate_target_path "var_dir" "$VAR_DIR"
export AI_WPS_STATE_DIR="$STATE_DIR"
export AI_WPS_BACKUP_DIR="$BACKUP_DIR"
export AI_WPS_VAR_DIR="$VAR_DIR"
recover_systemd_handoff
ensure_wps_processes_stopped
probe_current_install_readiness
stop_adapter_for_state_transition
reexec_as_target_if_needed

mkdir -p "$INSTALL_ROOT" "$RELEASES_DIR" "$WPS_JSADDONS_DIR" \
  "$BACKUP_DIR" "$VAR_DIR/logs" "$VAR_DIR/run" "$VAR_DIR/transactions"
chmod 700 "$INSTALL_ROOT" "$RELEASES_DIR" "$BACKUP_DIR" "$VAR_DIR" \
  "$VAR_DIR/logs" "$VAR_DIR/run" "$VAR_DIR/transactions"
recover_incomplete_transactions
resolve_active_adapter
if [ -f "$ADAPTER_TARGET/release-manifest.json" ]; then
  PREVIOUS_RELEASE_VERSION="$(
    "$PYTHON_BIN" -c \
      'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8")).get("version", "legacy"))' \
      "$ADAPTER_TARGET/release-manifest.json" 2>/dev/null || printf '%s' legacy
  )"
fi

TRANSACTION_ID="release-${RELEASE_VERSION}-$(date -u '+%Y%m%dT%H%M%SZ')-$$"
CANDIDATE_TARGET="$RELEASES_DIR/.${RELEASE_VERSION}.${TRANSACTION_ID}.candidate"
CANDIDATE_STATE="$(dirname "$STATE_DIR")/.ai-wps-${TRANSACTION_ID}-state.candidate"
PREFLIGHT_ROOT="$INSTALL_ROOT/.candidate-preflight-$$"
WORD_PLUGIN_CANDIDATE="$WPS_JSADDONS_DIR/.ai-wps-${TRANSACTION_ID}-${WORD_PLUGIN_NAME}.candidate"
EXCEL_PLUGIN_CANDIDATE="$WPS_JSADDONS_DIR/.ai-wps-${TRANSACTION_ID}-${EXCEL_PLUGIN_NAME}.candidate"
PPT_PLUGIN_CANDIDATE="$WPS_JSADDONS_DIR/.ai-wps-${TRANSACTION_ID}-${PPT_PLUGIN_NAME}.candidate"
PUBLISH_CANDIDATE="$WPS_JSADDONS_DIR/.ai-wps-${TRANSACTION_ID}-publish.xml.candidate"
CURRENT_CANDIDATE="$INSTALL_ROOT/.ai-wps-${TRANSACTION_ID}-current.candidate"
RELEASE_SWITCHED="0"
case "$PORT" in
  ''|*[!0-9]*) fail "runtime_port_invalid" ;;
esac
[ "$PORT" -ge 1 ] && [ "$PORT" -le 65535 ] || fail "runtime_port_invalid"
CANDIDATE_PORT="${AI_WPS_CANDIDATE_PORT:-$((PORT + 1000))}"
case "$CANDIDATE_PORT" in
  ''|*[!0-9]*) fail "isolated_port_invalid" ;;
esac
if [ "$CANDIDATE_PORT" -gt 65535 ]; then
  CANDIDATE_PORT="$((PORT - 1000))"
fi
[ "$CANDIDATE_PORT" -ge 1 ] && [ "$CANDIDATE_PORT" -le 65535 ] || fail "isolated_port_invalid"
[ "$CANDIDATE_PORT" != "$PORT" ] || fail "isolated_port_matches_runtime_port"

cleanup_installation_candidate() {
  local transaction_status=""
  if [ -n "${TRANSACTION_LOG:-}" ] && [ -f "$TRANSACTION_LOG" ]; then
    transaction_status="$(
      "$PYTHON_BIN" -c \
        'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8")).get("status", ""))' \
        "$TRANSACTION_LOG" 2>/dev/null || true
    )"
    if [ "${RELEASE_SWITCHED:-0}" = "1" ] \
      && [ "$transaction_status" != "committed" ] \
      && [ "$transaction_status" != "recovery_activated" ] \
      && [ "$transaction_status" != "ready_to_commit" ]; then
      ADAPTER_TARGET="$CURRENT_LINK"
      if [ -f "$ADAPTER_TARGET/scripts/stop_adapter.sh" ]; then
        AI_WPS_STATE_DIR="$STATE_DIR" \
          AI_WPS_BACKUP_DIR="$BACKUP_DIR" \
          AI_WPS_VAR_DIR="$VAR_DIR" \
          bash "$ADAPTER_TARGET/scripts/stop_adapter.sh" "$PORT" \
          || log "candidate_adapter_stop_failed=$ADAPTER_TARGET"
      fi
    fi
    case "$transaction_status" in
      committed|recovery_activated|rolled_back) ;;
      ready_to_commit)
        [ "${AI_WPS_DEFER_RELEASE_COMMIT:-0}" = "1" ] \
          || "$PYTHON_BIN" -s "$TRANSACTION_TOOL" rollback "$TRANSACTION_LOG"
        ;;
      *)
        "$PYTHON_BIN" -s "$TRANSACTION_TOOL" rollback "$TRANSACTION_LOG" \
          || log "release_transaction_rollback_failed=$TRANSACTION_LOG"
        ;;
    esac
  fi
  if [ "${RELEASE_SWITCHED:-0}" = "1" ] \
    && [ "$transaction_status" != "committed" ] \
    && [ "$transaction_status" != "recovery_activated" ] \
    && [ "$transaction_status" != "ready_to_commit" ]; then
    resolve_active_adapter
    restart_previous_adapter
  fi
  if [ "$PRESERVE_RECOVERY_CANDIDATE" != "1" ] \
    && [ -n "${CANDIDATE_TARGET:-}" ] \
    && { [ -e "$CANDIDATE_TARGET" ] || [ -L "$CANDIDATE_TARGET" ]; }; then
    rm -rf "$CANDIDATE_TARGET"
  fi
  if [ "$PRESERVE_RECOVERY_CANDIDATE" != "1" ] \
    && [ -n "${CANDIDATE_STATE:-}" ] \
    && { [ -e "$CANDIDATE_STATE" ] || [ -L "$CANDIDATE_STATE" ]; }; then
    rm -rf "$CANDIDATE_STATE"
  fi
  if [ -z "${TRANSACTION_LOG:-}" ] \
    && [ "$PRESERVE_RECOVERY_CANDIDATE" != "1" ] \
    && [ -n "${CANDIDATE_SNAPSHOT_ID:-}" ] \
    && [ -d "$BACKUP_DIR/$CANDIDATE_SNAPSHOT_ID" ]; then
    rm -rf "$BACKUP_DIR/$CANDIDATE_SNAPSHOT_ID"
  fi
  if [ -n "${PREFLIGHT_ROOT:-}" ] && [ -e "$PREFLIGHT_ROOT" ]; then
    rm -rf "$PREFLIGHT_ROOT"
  fi
  for candidate_path in \
    "${WORD_PLUGIN_CANDIDATE:-}" \
    "${EXCEL_PLUGIN_CANDIDATE:-}" \
    "${PPT_PLUGIN_CANDIDATE:-}" \
    "${PUBLISH_CANDIDATE:-}" \
    "${CURRENT_CANDIDATE:-}"; do
    if [ -n "$candidate_path" ] && { [ -e "$candidate_path" ] || [ -L "$candidate_path" ]; }; then
      rm -rf "$candidate_path"
    fi
  done
  if [ "$PRESERVE_RECOVERY_CANDIDATE" = "1" ] \
    && [ "${AI_WPS_SYSTEMD_MANAGED_BY_PARENT:-0}" != "1" ]; then
    restart_previous_adapter
  fi
}
trap cleanup_installation_candidate EXIT

log "phase1_install_start=true"
log "delivery_root=$DELIVERY_ROOT"
log "python=$($PYTHON_BIN --version 2>&1)"
log "target_user=$TARGET_USER target_uid=$TARGET_UID target_home=$TARGET_HOME"
log "wps_jsaddons_dir=$WPS_JSADDONS_DIR"
log "install_root=$INSTALL_ROOT"
log "candidate_port=$CANDIDATE_PORT"

prepare_candidate_adapter
prepare_runtime_state
initialize_writing_policy_database "$CANDIDATE_TARGET" "$CANDIDATE_STATE"
create_candidate_state_snapshot
run_candidate_preflight
enforce_recovery_activation_gate
stage_wps_plugins
write_generation_manifest
ln -s "$RELEASE_TARGET" "$CURRENT_CANDIDATE"
prepare_release_transaction
RELEASE_SWITCHED="1"
switch_release_generation
start_and_check_adapter
finalize_release_generation

cleanup_installation_candidate
trap - EXIT

if [ "$ACTIVATE_RECOVERY" = "1" ]; then
  if [ "${AI_WPS_DEFER_RELEASE_COMMIT:-0}" = "1" ]; then
    log "recovery_mode_activation_staged=true"
  else
    log "recovery_mode_activated=true"
  fi
  log "recovery_mode_scope=diagnostics,backup,restore"
else
  log "phase1_install_done=true"
  log "next_step=restart WPS, open WPS AI 助理 tab, then run scripts/phase1_smoke_test.sh"
fi
