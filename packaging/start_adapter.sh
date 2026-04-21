#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_DIR="${1:-$HOME/.wps-ai-assistant}"
PORT="${2:-18100}"

cd "$TARGET_DIR/adapter_service"
PYTHON_BIN="${PYTHON_BIN:-python3}"

exec "$PYTHON_BIN" -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT"
