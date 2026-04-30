#!/usr/bin/env bash
set -euo pipefail

KIT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${1:-18100}"

echo "restart_step=stop"
bash "$KIT_ROOT/scripts/stop_adapter.sh" "$PORT" || true

echo "restart_step=start"
bash "$KIT_ROOT/scripts/start_adapter.sh" "$PORT"

echo "restart_step=check"
bash "$KIT_ROOT/scripts/check_health.sh" "$PORT"

echo "restart_status=completed port=$PORT"
