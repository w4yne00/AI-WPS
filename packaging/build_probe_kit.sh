#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${1:-$ROOT_DIR/dist-probe-kit}"
KIT_NAME="wps-runtime-probe-kit-$(date '+%Y%m%d')"
TMP_DIR="$OUT_DIR/$KIT_NAME"

rm -rf "$TMP_DIR"
mkdir -p "$TMP_DIR"

cp -R "$ROOT_DIR/probe-kit/." "$TMP_DIR/"

tar -czf "$OUT_DIR/$KIT_NAME.tar.gz" -C "$OUT_DIR" "$KIT_NAME"

echo "Probe kit created at $OUT_DIR/$KIT_NAME.tar.gz"
