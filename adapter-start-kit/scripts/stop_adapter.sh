#!/usr/bin/env bash
set -euo pipefail

KIT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_FILE="$KIT_ROOT/run/adapter.pid"
PORT="${1:-18100}"

if [[ ! -f "$PID_FILE" ]]; then
  echo "adapter_not_running port=$PORT"
  exit 0
fi

PID="$(cat "$PID_FILE")"
if kill "$PID" >/dev/null 2>&1; then
  rm -f "$PID_FILE"
  echo "adapter_stopped pid=$PID"
else
  rm -f "$PID_FILE"
  echo "adapter_pid_stale pid=$PID"
fi
