#!/usr/bin/env bash

validate_adapter_runtime_path() {
  local name="$1"
  local value="$2"
  if [ -z "$value" ]; then
    return 0
  fi
  case "$value" in
    /*) ;;
    *)
      echo "runtime_path_invalid=$name reason=absolute_path_required" >&2
      return 1
      ;;
  esac
  case "$value" in
    *[[:cntrl:]]*)
      echo "runtime_path_invalid=$name reason=control_character_rejected" >&2
      return 1
      ;;
  esac
}

resolve_adapter_runtime_paths() {
  local kit_root="$1"
  local state_dir="${AI_WPS_STATE_DIR:-}"
  local configured_var_dir="${AI_WPS_VAR_DIR:-}"

  validate_adapter_runtime_path "AI_WPS_STATE_DIR" "$state_dir"
  validate_adapter_runtime_path "AI_WPS_BACKUP_DIR" "${AI_WPS_BACKUP_DIR:-}"
  validate_adapter_runtime_path "AI_WPS_VAR_DIR" "$configured_var_dir"

  if [ -n "$state_dir" ]; then
    local layout_root
    layout_root="$(dirname "$state_dir")"
    AI_WPS_BACKUP_DIR="${AI_WPS_BACKUP_DIR:-$layout_root/backups}"
    AI_WPS_VAR_DIR="${AI_WPS_VAR_DIR:-$layout_root/var}"
    ADAPTER_TRANSACTION_DIR="$AI_WPS_VAR_DIR/transactions"
    export AI_WPS_STATE_DIR AI_WPS_BACKUP_DIR AI_WPS_VAR_DIR
  elif [ -n "$configured_var_dir" ]; then
    AI_WPS_VAR_DIR="$configured_var_dir"
    AI_WPS_BACKUP_DIR="${AI_WPS_BACKUP_DIR:-$kit_root/backups}"
    ADAPTER_TRANSACTION_DIR="$AI_WPS_VAR_DIR/transactions"
    export AI_WPS_BACKUP_DIR AI_WPS_VAR_DIR
  else
    AI_WPS_VAR_DIR="$kit_root"
    AI_WPS_BACKUP_DIR="${AI_WPS_BACKUP_DIR:-$kit_root/backups}"
    ADAPTER_TRANSACTION_DIR="$kit_root/run/transactions"
  fi

  ADAPTER_LOG_DIR="$AI_WPS_VAR_DIR/logs"
  ADAPTER_RUN_DIR="$AI_WPS_VAR_DIR/run"
  ADAPTER_LOG_FILE="$ADAPTER_LOG_DIR/adapter.log"
  ADAPTER_PID_FILE="$ADAPTER_RUN_DIR/adapter.pid"
}
