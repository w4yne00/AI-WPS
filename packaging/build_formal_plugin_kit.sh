#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${1:-$ROOT_DIR/dist-formal-plugin-kit}"
KIT_NAME="wps-ai-assistant-kit-$(date '+%Y%m%d')"
TMP_DIR="$OUT_DIR/$KIT_NAME"

rm -rf "$TMP_DIR"
mkdir -p "$TMP_DIR"

cp -R "$ROOT_DIR/formal-plugin-kit/." "$TMP_DIR/"
find "$TMP_DIR" \( -name '.DS_Store' -o -name '._*' \) -delete

COPYFILE_DISABLE=1 tar -czf "$OUT_DIR/$KIT_NAME.tar.gz" -C "$OUT_DIR" "$KIT_NAME"

echo "Formal plugin kit created at $OUT_DIR/$KIT_NAME.tar.gz"
