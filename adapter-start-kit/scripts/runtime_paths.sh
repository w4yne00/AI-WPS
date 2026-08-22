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
  # Bash's [[:cntrl:]] is locale-dependent and misses Unicode Cc characters
  # such as U+0085 on Kylin. Scan UTF-8 bytes for C0/C1 controls instead.
  if runtime_path_contains_control_character "$value"; then
    echo "runtime_path_invalid=$name reason=control_character_rejected" >&2
    return 1
  fi
}

runtime_path_contains_control_character() (
  local value="$1"
  local byte next_byte
  local byte_value next_value
  local -i index length

  LC_ALL=C
  length=${#value}
  for ((index = 0; index < length; index++)); do
    byte="${value:index:1}"
    printf -v byte_value '%d' "'${byte}"
    if [ "$byte_value" -lt 0 ]; then
      byte_value=$((byte_value + 256))
    fi
    if [ "$byte_value" -lt 32 ] || [ "$byte_value" -eq 127 ]; then
      return 0
    fi
    if [ "$byte_value" -eq 194 ] && [ $((index + 1)) -lt "$length" ]; then
      next_byte="${value:$((index + 1)):1}"
      printf -v next_value '%d' "'${next_byte}"
      if [ "$next_value" -lt 0 ]; then
        next_value=$((next_value + 256))
      fi
      if [ "$next_value" -ge 128 ] && [ "$next_value" -le 159 ]; then
        return 0
      fi
    fi
  done
  return 1
)

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
