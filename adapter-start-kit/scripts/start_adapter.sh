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

read_health() {
  if command -v curl >/dev/null 2>&1; then
    curl -fsS "$HEALTH_URL" 2>/dev/null || true
  fi
}

detect_mode() {
  printf '%s' "$1" | sed -n 's/.*"mode"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1
}

kill_pid_if_running() {
  local pid="$1"
  if [ -n "$pid" ] && kill -0 "$pid" >/dev/null 2>&1; then
    kill "$pid" >/dev/null 2>&1 || true
    sleep 1
    if kill -0 "$pid" >/dev/null 2>&1; then
      kill -9 "$pid" >/dev/null 2>&1 || true
    fi
  fi
}

replace_existing_adapter() {
  local health_body="$1"
  local existing_mode
  existing_mode="$(detect_mode "$health_body")"
  echo "existing_adapter_detected=${existing_mode:-unknown} port=$PORT"

  if [ -f "$PID_FILE" ]; then
    kill_pid_if_running "$(cat "$PID_FILE" 2>/dev/null || true)"
    rm -f "$PID_FILE"
  fi

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

if "$PYTHON_BIN" -c "import uvicorn, fastapi" >/dev/null 2>&1; then
  MODE="uvicorn"
else
  MODE="standalone"
fi

HEALTH_BODY="$(read_health)"
if [ -n "$HEALTH_BODY" ]; then
  CURRENT_MODE="$(detect_mode "$HEALTH_BODY")"
  if [ "$CURRENT_MODE" = "$MODE" ]; then
    echo "adapter_already_running pid=unknown port=$PORT mode=$MODE"
    echo "adapter_health=reachable url=$HEALTH_URL"
    exit 0
  fi
  replace_existing_adapter "$HEALTH_BODY"
fi

cd "$KIT_ROOT/adapter_service"
if [ "$MODE" = "uvicorn" ]; then
  nohup "$PYTHON_BIN" -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" >> "$LOG_FILE" 2>&1 &
else
  nohup "$PYTHON_BIN" standalone_adapter.py "$PORT" >> "$LOG_FILE" 2>&1 &
fi

echo $! > "$PID_FILE"
PID="$(cat "$PID_FILE")"

for _ in 1 2 3 4 5; do
  HEALTH_BODY="$(read_health)"
  if [ -n "$HEALTH_BODY" ] && [ "$(detect_mode "$HEALTH_BODY")" = "$MODE" ]; then
    echo "adapter_started pid=$PID port=$PORT mode=$MODE log=$LOG_FILE"
    echo "adapter_health=reachable url=$HEALTH_URL"
    exit 0
  fi
  sleep 1
done

echo "adapter_start_failed pid=$PID port=$PORT log=$LOG_FILE"
echo "next_step=check logs with: tail -n 50 '$LOG_FILE'"
exit 1
