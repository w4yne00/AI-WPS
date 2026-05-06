#!/usr/bin/env bash
set -euo pipefail

PORT="${1:-18100}"
HEALTH_URL="http://127.0.0.1:${PORT}/health"

if ! command -v curl >/dev/null 2>&1; then
  echo "curl_missing"
  exit 1
fi

BODY="$(curl -fsS "$HEALTH_URL" 2>/dev/null || true)"

if [ -n "$BODY" ]; then
  printf '%s\n' "$BODY"
  MODE="$(printf '%s' "$BODY" | sed -n 's/.*"mode"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1)"
  echo
  echo "adapter_health=reachable url=$HEALTH_URL"
  if [ "$MODE" = "uvicorn" ]; then
    echo "adapter_mode=uvicorn"
    echo "adapter_runtime=fastapi"
  elif [ "$MODE" = "standalone" ]; then
    echo "adapter_mode=standalone"
    echo "hint=端口可达，但当前是 standalone 兼容模式；如需 FastAPI/uvicorn，请执行 bash scripts/start_uvicorn_adapter.sh ${PORT}，脚本会替换旧进程。"
  else
    echo "adapter_mode=${MODE:-unknown}"
  fi
  exit 0
fi

echo "adapter_health=unreachable url=$HEALTH_URL"
echo "possible_causes=service_not_started|startup_crash|wrong_port|local_firewall"
echo "next_step_1=bash scripts/status_adapter.sh ${PORT}"
echo "next_step_2=tail -n 50 ../logs/adapter.log"
exit 1
