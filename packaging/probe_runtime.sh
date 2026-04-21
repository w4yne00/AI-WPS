#!/usr/bin/env bash
set -euo pipefail

TARGET_DIR="${1:-$HOME/.wps-ai-assistant}"
OUT_FILE="${2:-$TARGET_DIR/runtime-probe.txt}"

mkdir -p "$(dirname "$OUT_FILE")"

{
  echo "== System =="
  echo "date=$(date '+%Y-%m-%d %H:%M:%S %z')"
  echo "kernel=$(uname -sr)"
  echo "machine=$(uname -m)"
  echo "shell=${SHELL:-unknown}"
  echo

  echo "== Python =="
  if command -v python3 >/dev/null 2>&1; then
    echo "python3_path=$(command -v python3)"
    echo "python3_version=$(python3 --version 2>&1)"
  else
    echo "python3_path=missing"
    echo "python3_version=missing"
  fi
  echo

  echo "== WPS Binaries =="
  for bin_name in wps wpp et; do
    if command -v "$bin_name" >/dev/null 2>&1; then
      echo "${bin_name}_path=$(command -v "$bin_name")"
    else
      echo "${bin_name}_path=missing"
    fi
  done
  echo

  echo "== Deployment Layout =="
  for path in \
    "$TARGET_DIR/adapter_service/app/main.py" \
    "$TARGET_DIR/wps-addon/manifest.xml" \
    "$TARGET_DIR/templates/general/general-office.json" \
    "$TARGET_DIR/config/adapter.example.json"; do
    if [[ -e "$path" ]]; then
      echo "present=$path"
    else
      echo "missing=$path"
    fi
  done
  echo

  echo "== Adapter Health =="
  if command -v curl >/dev/null 2>&1; then
    if curl -fsS "http://127.0.0.1:18100/health" >/dev/null 2>&1; then
      echo "adapter_health=reachable"
      curl -fsS "http://127.0.0.1:18100/health"
      echo
    else
      echo "adapter_health=unreachable"
    fi
  else
    echo "adapter_health=curl-missing"
  fi
} > "$OUT_FILE"

echo "Runtime probe written to $OUT_FILE"
