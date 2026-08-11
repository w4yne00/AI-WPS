#!/usr/bin/env bash

systemd_quote_value() {
  local value="$1"
  case "$value" in
    *[[:cntrl:]]*)
      echo "systemd_value_invalid=control_character_rejected" >&2
      return 1
      ;;
  esac
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  value="${value//%/%%}"
  printf '"%s"' "$value"
}

render_adapter_systemd_unit() {
  local output_path="$1"
  local service_user="$2"
  local kit_root="$3"
  local python_bin="$4"
  local port="$5"
  local pid_file="$6"
  local requested_state_dir="$7"
  local requested_backup_dir="$8"
  local requested_var_dir="$9"
  local quoted_user quoted_root quoted_python quoted_pid quoted_start quoted_stop quoted_port
  local quoted_environment
  local runtime_environment_lines=""

  quoted_user="$(systemd_quote_value "$service_user")" || return 1
  quoted_root="$(systemd_quote_value "$kit_root")" || return 1
  quoted_python="$(systemd_quote_value "PYTHON_BIN=$python_bin")" || return 1
  quoted_pid="$(systemd_quote_value "$pid_file")" || return 1
  quoted_start="$(systemd_quote_value "$kit_root/scripts/start_adapter.sh")" || return 1
  quoted_stop="$(systemd_quote_value "$kit_root/scripts/stop_adapter.sh")" || return 1
  quoted_port="$(systemd_quote_value "$port")" || return 1

  if [ -n "$requested_state_dir" ]; then
    quoted_environment="$(systemd_quote_value "AI_WPS_STATE_DIR=$requested_state_dir")" || return 1
    runtime_environment_lines="Environment=$quoted_environment"
  fi
  if [ -n "$requested_backup_dir" ]; then
    quoted_environment="$(systemd_quote_value "AI_WPS_BACKUP_DIR=$requested_backup_dir")" || return 1
    runtime_environment_lines="${runtime_environment_lines}${runtime_environment_lines:+$'\n'}Environment=$quoted_environment"
  fi
  if [ -n "$requested_var_dir" ]; then
    quoted_environment="$(systemd_quote_value "AI_WPS_VAR_DIR=$requested_var_dir")" || return 1
    runtime_environment_lines="${runtime_environment_lines}${runtime_environment_lines:+$'\n'}Environment=$quoted_environment"
  fi

  cat > "$output_path" <<EOF
[Unit]
Description=AI-WPS local adapter
After=network-online.target
Wants=network-online.target

[Service]
Type=forking
User=$quoted_user
WorkingDirectory=$quoted_root
Environment=$quoted_python
$runtime_environment_lines
PIDFile=$quoted_pid
ExecStart=/bin/bash $quoted_start $quoted_port
ExecStop=/bin/bash $quoted_stop $quoted_port
Restart=on-failure
RestartSec=10
TimeoutStartSec=30
TimeoutStopSec=20

[Install]
WantedBy=multi-user.target
EOF
}
