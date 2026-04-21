#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${1:-$ROOT_DIR/dist-offline}"

mkdir -p "$OUT_DIR"
tar -czf "$OUT_DIR/wps-ai-assistant-offline.tar.gz" \
  -C "$ROOT_DIR" \
  adapter_service \
  config \
  packaging \
  templates \
  wps-addon

echo "Offline bundle created at $OUT_DIR/wps-ai-assistant-offline.tar.gz"
