#!/usr/bin/env bash
set -euo pipefail

KIT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_FILE="$KIT_ROOT/run/adapter.pid"

if [[ ! -f "$PID_FILE" ]]; then
  echo "adapter_status=stopped"
  exit 0
fi

PID="$(cat "$PID_FILE")"
if kill -0 "$PID" >/dev/null 2>&1; then
  echo "adapter_status=running pid=$PID"
else
  echo "adapter_status=stale pid=$PID"
fi
