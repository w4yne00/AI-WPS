#!/usr/bin/env bash
set -euo pipefail

KIT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${1:-18100}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
EXPECTED_VERSION="${EXPECTED_VERSION:-0.18.1-alpha}"
PID_FILE="$KIT_ROOT/run/adapter.pid"
LOG_DIR="$KIT_ROOT/logs"
LOG_FILE="$LOG_DIR/adapter.log"
HEALTH_URL="http://127.0.0.1:${PORT}/health"

mkdir -p "$KIT_ROOT/run" "$LOG_DIR"

if ! "$PYTHON_BIN" -c "import uvicorn, fastapi" >/dev/null 2>&1; then
  echo "uvicorn_runtime_missing=true"
  echo "请先安装离线运行依赖：python3 -m pip install --no-index --find-links <runtime-deps>/wheels -r <runtime-deps>/requirements-runtime.txt"
  exit 1
fi

read_health() {
  if command -v curl >/dev/null 2>&1; then
    curl -fsS "$HEALTH_URL" 2>/dev/null || true
  fi
}

detect_mode() {
  printf '%s' "$1" | sed -n 's/.*"mode"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1
}

detect_version() {
  printf '%s' "$1" | sed -n 's/.*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1
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

HEALTH_BODY="$(read_health)"
if [ -n "$HEALTH_BODY" ]; then
  CURRENT_MODE="$(detect_mode "$HEALTH_BODY")"
  CURRENT_VERSION="$(detect_version "$HEALTH_BODY")"
  if [ "$CURRENT_MODE" = "uvicorn" ]; then
    if [ "$CURRENT_VERSION" = "$EXPECTED_VERSION" ] && [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" >/dev/null 2>&1; then
      echo "adapter_already_running pid=$(cat "$PID_FILE") port=$PORT mode=uvicorn"
      echo "adapter_health=reachable url=$HEALTH_URL version=${CURRENT_VERSION:-unknown}"
      exit 0
    fi
    echo "adapter_stale_running mode=uvicorn current_version=${CURRENT_VERSION:-unknown} expected_version=$EXPECTED_VERSION port=$PORT"
    replace_existing_adapter "$HEALTH_BODY"
  else
    replace_existing_adapter "$HEALTH_BODY"
  fi
fi

cd "$KIT_ROOT/adapter_service"
nohup "$PYTHON_BIN" -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" >> "$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"
PID="$(cat "$PID_FILE")"

for _ in 1 2 3 4 5 6 7 8; do
  HEALTH_BODY="$(read_health)"
  if [ -n "$HEALTH_BODY" ] && [ "$(detect_mode "$HEALTH_BODY")" = "uvicorn" ] && [ "$(detect_version "$HEALTH_BODY")" = "$EXPECTED_VERSION" ]; then
    echo "adapter_started pid=$PID port=$PORT mode=uvicorn log=$LOG_FILE"
    echo "adapter_health=reachable url=$HEALTH_URL version=$EXPECTED_VERSION"
    exit 0
  fi
  sleep 1
done

echo "adapter_start_failed pid=$PID port=$PORT mode=uvicorn log=$LOG_FILE"
echo "port_hint=如果健康检查仍返回 mode=standalone，说明旧进程仍占用 ${PORT}，请执行 bash scripts/stop_adapter.sh ${PORT} 后重试"
echo "next_step=tail -n 80 '$LOG_FILE'"
exit 1
