#!/usr/bin/env bash
set -euo pipefail

KIT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_FILE="$KIT_ROOT/run/adapter.pid"
PORT="${1:-18100}"
HEALTH_URL="http://127.0.0.1:${PORT}/health"

if [[ ! -f "$PID_FILE" ]]; then
  echo "adapter_status=stopped"
  exit 0
fi

PID="$(cat "$PID_FILE")"
if kill -0 "$PID" >/dev/null 2>&1; then
  echo "adapter_status=running pid=$PID"
  if command -v curl >/dev/null 2>&1; then
    if curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
      echo "adapter_health=reachable url=$HEALTH_URL"
    else
      echo "adapter_health=unreachable url=$HEALTH_URL"
    fi
  fi
else
  echo "adapter_status=stale pid=$PID"
fi
