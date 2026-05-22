#!/usr/bin/env bash
set -euo pipefail

KIT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_FILE="$KIT_ROOT/run/adapter.pid"
PORT="${1:-18100}"

kill_pid_if_running() {
  local pid="$1"
  if [ -n "$pid" ] && kill -0 "$pid" >/dev/null 2>&1; then
    kill "$pid" >/dev/null 2>&1 || true
    sleep 1
    if kill -0 "$pid" >/dev/null 2>&1; then
      kill -9 "$pid" >/dev/null 2>&1 || true
    fi
    echo "adapter_pid_stopped pid=$pid"
  fi
}

stop_port_listener() {
  if command -v lsof >/dev/null 2>&1; then
    for pid in $(lsof -ti TCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true); do
      kill_pid_if_running "$pid"
    done
  elif command -v fuser >/dev/null 2>&1; then
    fuser -k "${PORT}/tcp" >/dev/null 2>&1 || true
    sleep 1
  elif command -v ss >/dev/null 2>&1; then
    for pid in $(ss -ltnp "sport = :$PORT" 2>/dev/null | sed -n 's/.*pid=\([0-9]\+\).*/\1/p' | sort -u); do
      kill_pid_if_running "$pid"
    done
  fi
}

if [ -f "$PID_FILE" ]; then
  kill_pid_if_running "$(cat "$PID_FILE" 2>/dev/null || true)"
  rm -f "$PID_FILE"
else
  echo "adapter_pid_file=missing port=$PORT"
fi

stop_port_listener
echo "adapter_stopped port=$PORT"
