#!/usr/bin/env bash
set -euo pipefail

PORT="${1:-18100}"
HEALTH_URL="http://127.0.0.1:${PORT}/health"

if ! command -v curl >/dev/null 2>&1; then
  echo "curl_missing"
  exit 1
fi

if curl -fsS "$HEALTH_URL"; then
  echo
  echo "adapter_health=reachable url=$HEALTH_URL"
  exit 0
fi

echo "adapter_health=unreachable url=$HEALTH_URL"
echo "possible_causes=service_not_started|startup_crash|wrong_port|local_firewall"
echo "next_step_1=bash scripts/status_adapter.sh ${PORT}"
echo "next_step_2=tail -n 50 ../logs/adapter.log"
exit 1
