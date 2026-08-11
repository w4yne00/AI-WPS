#!/usr/bin/env bash
set -euo pipefail

DELIVERY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
PORT="${PORT:-18100}"
TARGET_USER_ARG=""
TARGET_UID_ARG=""
TARGET_HOME_ARG=""
WPS_JSADDONS_DIR_ARG=""

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
ADAPTER_TARGET=""
STATE_DIR=""
BACKUP_DIR=""
VAR_DIR=""
RELEASE_VERSION="0.23.1-alpha"

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
      *)
        fail "unknown_argument value=$1"
        ;;
    esac
  done
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
  local service_name="${SERVICE_NAME:-ai-wps-adapter.service}"
  if command -v systemctl >/dev/null 2>&1 \
    && systemctl is-active --quiet "$service_name"; then
    [ "$(id -u)" = "0" ] || fail "adapter_service_stop_requires_admin service=$service_name"
    systemctl stop "$service_name" || fail "adapter_service_stop_failed service=$service_name"
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

reexec_as_target_if_needed() {
  [ "$CURRENT_UID" = "0" ] || return 0
  if command -v runuser >/dev/null 2>&1; then
    exec runuser -u "$TARGET_USER" -- env \
      HOME="$TARGET_HOME" \
      AI_WPS_INSTALL_ROOT="$INSTALL_ROOT" \
      WPS_JSADDONS_DIR="$WPS_JSADDONS_DIR" \
      AI_WPS_STATE_DIR="$STATE_DIR" \
      AI_WPS_BACKUP_DIR="$BACKUP_DIR" \
      AI_WPS_VAR_DIR="$VAR_DIR" \
      PYTHON_BIN="$PYTHON_BIN" \
      PORT="$PORT" \
      AI_WPS_CANDIDATE_PORT="${AI_WPS_CANDIDATE_PORT:-}" \
      bash "$DELIVERY_ROOT/installer/install_phase1.sh" \
        --target-user "$TARGET_USER" \
        --target-uid "$TARGET_UID" \
        --target-home "$TARGET_HOME" \
        --wps-jsaddons-dir "$WPS_JSADDONS_DIR"
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

initialize_writing_policy_database() {
  local database_root="${STATE_DIR:-$ADAPTER_TARGET/run}"
  local database_path="$database_root/writing_policies.db"
  local adapter_pythonpath="$ADAPTER_TARGET/adapter_service"

  if [ -d "$ADAPTER_TARGET/python-runtime" ]; then
    adapter_pythonpath="$ADAPTER_TARGET/python-runtime:$adapter_pythonpath"
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
  local result
  local candidate_state_tool="$CANDIDATE_TARGET/adapter_service/tools/runtime_state.py"
  local candidate_pythonpath="$CANDIDATE_TARGET/python-runtime:$CANDIDATE_TARGET/adapter_service"

  [ -f "$candidate_state_tool" ] || fail "runtime_state_tool_missing"
  mkdir -p "$STATE_DIR" "$BACKUP_DIR" "$VAR_DIR/logs" "$VAR_DIR/run" "$VAR_DIR/transactions"
  chmod 700 "$STATE_DIR" "$BACKUP_DIR" "$VAR_DIR" \
    "$VAR_DIR/logs" "$VAR_DIR/run" "$VAR_DIR/transactions"

  if runtime_state_exists; then
    result="$(
      PYTHONNOUSERSITE=1 PYTHONPATH="$candidate_pythonpath" \
        "$PYTHON_BIN" -s "$candidate_state_tool" snapshot \
        --state-dir "$STATE_DIR" \
        --backup-dir "$BACKUP_DIR" \
        --release-version "$RELEASE_VERSION" \
        --reason pre_install
    )" || fail "runtime_state_snapshot_failed"
    log "runtime_state_snapshot_reason=pre_install"
    case "$result" in
      *'"status": "recovery"'*) fail "runtime_state_snapshot_status=recovery" ;;
      *'"status": "degraded"'*) log "runtime_state_snapshot_status=degraded" ;;
      *) log "runtime_state_snapshot_status=ready" ;;
    esac
    return 0
  fi

  if legacy_runtime_state_exists; then
    result="$(
      PYTHONNOUSERSITE=1 PYTHONPATH="$candidate_pythonpath" \
        "$PYTHON_BIN" -s "$candidate_state_tool" migrate \
        --state-dir "$STATE_DIR" \
        --backup-dir "$BACKUP_DIR" \
        --release-version "$RELEASE_VERSION" \
        --legacy-root "$ADAPTER_TARGET"
    )" || fail "runtime_state_migration_status=recovery"
    case "$result" in
      *'"status": "degraded"'*) log "runtime_state_migration_status=degraded" ;;
      *) log "runtime_state_migration_status=ready" ;;
    esac
    return 0
  fi

  log "runtime_state_status=fresh"
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

  mkdir -p "$INSTALL_ROOT"
  copy_dir "$ADAPTER_SOURCE" "$CANDIDATE_TARGET"
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
  bash "$DELIVERY_ROOT/installer/preflight_candidate.sh" \
    "$PYTHON_BIN" \
    "$CANDIDATE_TARGET" \
    "$CANDIDATE_TARGET/python-runtime" \
    "$CANDIDATE_PORT" \
    "$RELEASE_VERSION" \
    "$PREFLIGHT_ROOT"
}

install_wps_plugin() {
  [ -d "$WORD_PLUGIN_SOURCE" ] || fail "word_plugin_source_missing"
  [ -d "$EXCEL_PLUGIN_SOURCE" ] || fail "excel_plugin_source_missing"
  [ -d "$PPT_PLUGIN_SOURCE" ] || fail "ppt_plugin_source_missing"
  [ -f "$PUBLISH_SOURCE" ] || fail "publish_xml_missing"

  mkdir -p "$WPS_JSADDONS_DIR"
  copy_dir "$WORD_PLUGIN_SOURCE" "$WPS_JSADDONS_DIR/$WORD_PLUGIN_NAME"
  copy_dir "$EXCEL_PLUGIN_SOURCE" "$WPS_JSADDONS_DIR/$EXCEL_PLUGIN_NAME"
  copy_dir "$PPT_PLUGIN_SOURCE" "$WPS_JSADDONS_DIR/$PPT_PLUGIN_NAME"

  if [ -f "$WPS_JSADDONS_DIR/publish.xml" ]; then
    cp "$WPS_JSADDONS_DIR/publish.xml" "$WPS_JSADDONS_DIR/publish.xml.bak.$(date '+%Y%m%d%H%M%S')"
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
    } > "$WPS_JSADDONS_DIR/publish.xml.tmp"
    mv "$WPS_JSADDONS_DIR/publish.xml.tmp" "$WPS_JSADDONS_DIR/publish.xml"
  else
    cp "$PUBLISH_SOURCE" "$WPS_JSADDONS_DIR/publish.xml"
  fi

  log "word_plugin_installed=$WPS_JSADDONS_DIR/$WORD_PLUGIN_NAME"
  log "excel_plugin_installed=$WPS_JSADDONS_DIR/$EXCEL_PLUGIN_NAME"
  log "ppt_plugin_installed=$WPS_JSADDONS_DIR/$PPT_PLUGIN_NAME"
  log "publish_xml_installed=$WPS_JSADDONS_DIR/publish.xml"
}

install_adapter() {
  [ -d "$CANDIDATE_TARGET" ] || fail "candidate_adapter_missing"
  stop_adapter_for_state_transition
  prepare_runtime_state
  rm -rf "$ADAPTER_TARGET"
  mv "$CANDIDATE_TARGET" "$ADAPTER_TARGET"
  CANDIDATE_TARGET=""
  initialize_writing_policy_database
  enable_exec_permissions
  log "adapter_installed=$ADAPTER_TARGET"
}

start_and_check_adapter() {
  log "adapter_start=uvicorn port=$PORT"
  AI_WPS_REQUIRE_PRIVATE_RUNTIME=1 \
    bash "$ADAPTER_TARGET/scripts/start_uvicorn_adapter.sh" "$PORT"
  bash "$ADAPTER_TARGET/scripts/check_health.sh" "$PORT"
}

parse_arguments "$@"
resolve_installation_principal
resolve_python_binary
ADAPTER_TARGET="$INSTALL_ROOT/adapter-start-kit"
STATE_DIR="${AI_WPS_STATE_DIR:-$INSTALL_ROOT/state}"
BACKUP_DIR="${AI_WPS_BACKUP_DIR:-$INSTALL_ROOT/backups}"
VAR_DIR="${AI_WPS_VAR_DIR:-$INSTALL_ROOT/var}"
validate_target_path "state_dir" "$STATE_DIR"
validate_target_path "backup_dir" "$BACKUP_DIR"
validate_target_path "var_dir" "$VAR_DIR"
export AI_WPS_STATE_DIR="$STATE_DIR"
export AI_WPS_BACKUP_DIR="$BACKUP_DIR"
export AI_WPS_VAR_DIR="$VAR_DIR"
ensure_wps_processes_stopped
stop_adapter_for_state_transition
reexec_as_target_if_needed

CANDIDATE_TARGET="$INSTALL_ROOT/.adapter-candidate-${RELEASE_VERSION}-$$"
PREFLIGHT_ROOT="$INSTALL_ROOT/.candidate-preflight-$$"
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
  if [ -n "${CANDIDATE_TARGET:-}" ] && [ -e "$CANDIDATE_TARGET" ]; then
    rm -rf "$CANDIDATE_TARGET"
  fi
  if [ -n "${PREFLIGHT_ROOT:-}" ] && [ -e "$PREFLIGHT_ROOT" ]; then
    rm -rf "$PREFLIGHT_ROOT"
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
run_candidate_preflight
install_wps_plugin
install_adapter
start_and_check_adapter

cleanup_installation_candidate
trap - EXIT

log "phase1_install_done=true"
log "next_step=restart WPS, open WPS AI 助理 tab, then run scripts/phase1_smoke_test.sh"
