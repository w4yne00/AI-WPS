#!/usr/bin/env bash
set -euo pipefail

if [ "${AI_WPS_DESKTOP_LAUNCH:-0}" = "1" ]; then
  trap '
    restart_exit_code=$?
    if [ "$restart_exit_code" -ne 0 ] && [ -t 0 ]; then
      echo "后台服务重启失败（退出码：${restart_exit_code}），请查看上方错误信息，按回车键关闭窗口。" >&2
      read -r restart_close_window || true
    fi
    exit "$restart_exit_code"
  ' EXIT
fi

KIT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${1:-18100}"
SERVICE_NAME="${SERVICE_NAME:-ai-wps-adapter.service}"
SERVICE_FILE="${AI_WPS_SYSTEMD_SERVICE_FILE:-/etc/systemd/system/$SERVICE_NAME}"

source "$KIT_ROOT/scripts/runtime_paths.sh"
resolve_adapter_runtime_paths "$KIT_ROOT"
ADAPTER_APP_ROOT="$(cd -P "$KIT_ROOT/adapter_service" && pwd -P)"
RUNTIME_PID="$(cat "$ADAPTER_PID_FILE" 2>/dev/null || true)"

is_current_adapter() {
  local pid="$1" process_root process_command
  [ -n "$RUNTIME_PID" ] && [ "$pid" = "$RUNTIME_PID" ] || return 1
  process_root="$(readlink "/proc/$pid/cwd" 2>/dev/null || true)"
  [ "$process_root" = "$ADAPTER_APP_ROOT" ] || return 1
  process_command="$(ps -p "$pid" -o args= 2>/dev/null || true)"
  case " $process_command " in
    *" -m uvicorn app.main:app "*|*" standalone_adapter.py "*) return 0 ;;
    *) return 1 ;;
  esac
}

if command -v lsof >/dev/null 2>&1; then
  LISTENER_PIDS="$(lsof -ti TCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true)"
elif command -v fuser >/dev/null 2>&1; then
  LISTENER_PIDS="$(fuser "${PORT}/tcp" 2>/dev/null || true)"
elif command -v ss >/dev/null 2>&1; then
  LISTENERS="$(ss -H -ltnp "sport = :$PORT")"
  LISTENER_PIDS="$(printf '%s\n' "$LISTENERS" | sed -n 's/.*pid=\([0-9]\+\).*/\1/p' | sort -u)"
  if [ -n "$LISTENERS" ] && [ -z "$LISTENER_PIDS" ]; then
    echo "restart_failed=unrecognized_port_listener port=$PORT" >&2
    exit 1
  fi
else
  echo "restart_failed=port_inspection_unavailable port=$PORT" >&2
  exit 1
fi
for pid in $LISTENER_PIDS; do
  if ! is_current_adapter "$pid"; then
    echo "restart_failed=unrecognized_port_listener port=$PORT pid=$pid" >&2
    echo "端口由无法确认归属的进程占用，已保留该进程，请先核查。" >&2
    exit 1
  fi
done
if [ -z "$LISTENER_PIDS" ] && ( : >/dev/tcp/127.0.0.1/"$PORT") 2>/dev/null; then
  echo "restart_failed=unrecognized_port_listener port=$PORT" >&2
  exit 1
fi

if [ -f "$SERVICE_FILE" ]; then
  echo "restart_step=systemd service=$SERVICE_NAME"
  echo "正在通过系统服务重启后台；系统可能要求输入管理员密码。"
  if ! systemctl restart "$SERVICE_NAME"; then
    echo "restart_failed=systemd service=$SERVICE_NAME" >&2
    exit 1
  fi
else
  if [ -n "$RUNTIME_PID" ] && kill -0 "$RUNTIME_PID" 2>/dev/null && ! is_current_adapter "$RUNTIME_PID"; then
    rm -f "$ADAPTER_PID_FILE"
    echo "adapter_pid_file=stale_removed pid=$RUNTIME_PID"
  else
    echo "restart_step=stop"
    bash "$KIT_ROOT/scripts/stop_adapter.sh" "$PORT"
  fi

  echo "restart_step=start"
  bash "$KIT_ROOT/scripts/start_uvicorn_adapter.sh" "$PORT"
fi

echo "restart_step=check"
bash "$KIT_ROOT/scripts/check_health.sh" "$PORT"

echo "restart_status=completed port=$PORT"
