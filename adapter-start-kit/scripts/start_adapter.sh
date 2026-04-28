#!/usr/bin/env bash
set -euo pipefail

KIT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${1:-18100}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
PID_FILE="$KIT_ROOT/run/adapter.pid"
LOG_DIR="$KIT_ROOT/logs"
LOG_FILE="$LOG_DIR/adapter.log"
HEALTH_URL="http://127.0.0.1:${PORT}/health"

mkdir -p "$KIT_ROOT/run" "$LOG_DIR"

cd "$KIT_ROOT/adapter_service"
if "$PYTHON_BIN" -c "import uvicorn" >/dev/null 2>&1; then
  nohup "$PYTHON_BIN" -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" >> "$LOG_FILE" 2>&1 &
  MODE="uvicorn"
else
  nohup "$PYTHON_BIN" standalone_adapter.py "$PORT" >> "$LOG_FILE" 2>&1 &
  MODE="standalone"
fi

echo $! > "$PID_FILE"
PID="$(cat "$PID_FILE")"

for _ in 1 2 3 4 5; do
  if command -v curl >/dev/null 2>&1 && curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
    echo "adapter_started pid=$PID port=$PORT mode=$MODE log=$LOG_FILE"
    echo "adapter_health=reachable url=$HEALTH_URL"
    exit 0
  fi
  sleep 1
done

echo "adapter_start_failed pid=$PID port=$PORT log=$LOG_FILE"
echo "next_step=check logs with: tail -n 50 '$LOG_FILE'"
exit 1
