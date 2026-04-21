#!/usr/bin/env bash
set -euo pipefail

TARGET_DIR="${1:-$HOME/.wps-ai-assistant}"
STATUS=0

check_path() {
  local path="$1"
  if [[ -e "$path" ]]; then
    echo "[OK] $path"
  else
    echo "[MISSING] $path"
    STATUS=1
  fi
}

check_path "$TARGET_DIR/adapter_service/app/main.py"
check_path "$TARGET_DIR/wps-addon/manifest.xml"
check_path "$TARGET_DIR/templates/general/general-office.json"
check_path "$TARGET_DIR/config/adapter.example.json"

if command -v curl >/dev/null 2>&1; then
  if curl -fsS "http://127.0.0.1:18100/health" >/dev/null 2>&1; then
    echo "[OK] adapter health endpoint reachable"
  else
    echo "[WARN] adapter health endpoint not reachable on 127.0.0.1:18100"
  fi
fi

exit "$STATUS"
