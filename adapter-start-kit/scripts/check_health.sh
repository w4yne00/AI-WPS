#!/usr/bin/env bash
set -euo pipefail

PORT="${1:-18100}"
BASE_URL="http://127.0.0.1:${PORT}"
HEALTH_URL="$BASE_URL/health"
STATUS_URL="$BASE_URL/provider/status"
ROUTE_URL="$BASE_URL/provider/route-diagnostics"
DEBUG_URL="$BASE_URL/provider/debug-last"

if ! command -v curl >/dev/null 2>&1; then
  echo "curl_missing"
  exit 1
fi

read_endpoint() {
  curl -fsS "$1" 2>/dev/null || true
}

json_value() {
  printf '%s' "$1" | sed -n 's/.*"'"$2"'"[[:space:]]*:[[:space:]]*"\{0,1\}\([^",}]*\)"\{0,1\}.*/\1/p' | head -n 1
}

print_endpoint() {
  local label="$1"
  local url="$2"
  local body
  body="$(read_endpoint "$url")"
  if [ -n "$body" ]; then
    echo "${label}=reachable url=$url"
    printf '%s\n' "$body"
  else
    echo "${label}=unreachable url=$url"
  fi
  echo
}

HEALTH_BODY="$(read_endpoint "$HEALTH_URL")"
if [ -z "$HEALTH_BODY" ]; then
  echo "adapter_health=unreachable url=$HEALTH_URL"
  echo "possible_causes=service_not_started|startup_crash|wrong_port|local_firewall"
  echo "next_step_1=bash scripts/status_adapter.sh ${PORT}"
  echo "next_step_2=bash scripts/show_logs.sh 80"
  exit 1
fi

printf '%s\n' "$HEALTH_BODY"
MODE="$(json_value "$HEALTH_BODY" mode)"
VERSION="$(json_value "$HEALTH_BODY" version)"
PROVIDER_CONFIGURED="$(json_value "$HEALTH_BODY" providerConfigured)"
AUTH_SOURCE="$(json_value "$HEALTH_BODY" providerAuthSource)"
echo
echo "adapter_health=reachable url=$HEALTH_URL"
if [ "$MODE" = "uvicorn" ]; then
  echo "adapter_mode=uvicorn"
  echo "adapter_runtime=fastapi"
elif [ "$MODE" = "standalone" ]; then
  echo "adapter_mode=standalone"
else
  echo "adapter_mode=${MODE:-unknown}"
fi
echo "adapter_version=${VERSION:-unknown}"
echo "provider_configured=${PROVIDER_CONFIGURED:-unknown}"
echo "provider_auth_source=${AUTH_SOURCE:-unknown}"
if [ "$MODE" != "uvicorn" ]; then
  echo "hint=当前不是 uvicorn；执行 bash scripts/restart_adapter.sh ${PORT} 切换到 uvicorn。"
fi
if [ "$PROVIDER_CONFIGURED" != "true" ]; then
  echo "hint=provider 未配置完整；真实转发需要同时保存 API URL 和统一 Dify API Key，否则日志会出现 provider=mock。"
fi
echo

print_endpoint "provider_status" "$STATUS_URL"
print_endpoint "provider_route_diagnostics" "$ROUTE_URL"
print_endpoint "provider_debug_last" "$DEBUG_URL"
