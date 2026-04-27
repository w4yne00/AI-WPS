#!/usr/bin/env bash
set -euo pipefail

KIT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_FILE="$KIT_ROOT/logs/adapter.log"
LINES="${1:-50}"

if [[ ! -f "$LOG_FILE" ]]; then
  echo "log_missing path=$LOG_FILE"
  exit 1
fi

tail -n "$LINES" "$LOG_FILE"
