#!/usr/bin/env bash
set -euo pipefail

KIT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$KIT_ROOT/scripts/runtime_paths.sh"
resolve_adapter_runtime_paths "$KIT_ROOT"
PID_FILE="$ADAPTER_PID_FILE"
PORT="${1:-18100}"
BASE_URL="http://127.0.0.1:${PORT}"
LIVE_URL="$BASE_URL/health/live"
HEALTH_URL="$BASE_URL/health"
PROVIDER_STATUS_URL="$BASE_URL/provider/status"

read_endpoint() {
  if command -v curl >/dev/null 2>&1; then
    curl -fsS "$1" 2>/dev/null || true
  fi
}

print_health() {
  local live_body
  local health_body
  live_body="$(read_endpoint "$LIVE_URL")"
  health_body="$(read_endpoint "$HEALTH_URL")"
  if [ -n "$live_body" ]; then
    echo "adapter_health=reachable url=$LIVE_URL"
    printf '%s\n' "$live_body"
  else
    echo "adapter_health=unreachable url=$LIVE_URL"
  fi
  if [ -n "$health_body" ]; then
    echo "adapter_business_health=reachable url=$HEALTH_URL"
    printf '%s\n' "$health_body"
  else
    echo "adapter_business_health=unreachable url=$HEALTH_URL"
  fi
}

print_provider_status() {
  local status_body
  status_body="$(read_endpoint "$PROVIDER_STATUS_URL")"
  if [ -n "$status_body" ]; then
    echo "provider_status=reachable url=$PROVIDER_STATUS_URL"
    printf '%s\n' "$status_body"
  else
    echo "provider_status=unreachable url=$PROVIDER_STATUS_URL"
  fi
}

if [ ! -f "$PID_FILE" ]; then
  if [ -n "$(read_endpoint "$LIVE_URL")" ]; then
    echo "adapter_status=running pid=untracked port=$PORT"
    print_health
    print_provider_status
    exit 0
  fi
  echo "adapter_status=stopped port=$PORT"
  exit 0
fi

PID="$(cat "$PID_FILE")"
if kill -0 "$PID" >/dev/null 2>&1; then
  echo "adapter_status=running pid=$PID port=$PORT"
else
  echo "adapter_status=stale pid=$PID port=$PORT"
fi

print_health
print_provider_status
