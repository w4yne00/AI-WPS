#!/usr/bin/env bash
set -euo pipefail

KIT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_FILE="${1:-$KIT_ROOT/runtime-probe.txt}"

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

  echo "== Probe Kit Layout =="
  for path in \
    "$KIT_ROOT/wps-probe-addon/index.html" \
    "$KIT_ROOT/wps-probe-addon/main.js" \
    "$KIT_ROOT/wps-probe-addon/ribbon.js" \
    "$KIT_ROOT/wps-probe-addon/manifest.xml" \
    "$KIT_ROOT/wps-probe-addon/manifest.json" \
    "$KIT_ROOT/wps-probe-addon/ribbon.xml" \
    "$KIT_ROOT/wps-probe-addon/taskpane.html" \
    "$KIT_ROOT/wps-probe-addon/taskpane.js"; do
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
