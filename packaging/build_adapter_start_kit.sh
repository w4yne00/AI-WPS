#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${1:-$ROOT_DIR/dist-adapter-start-kit}"
KIT_NAME="adapter-start-kit-$(date '+%Y%m%d')"
TMP_DIR="$OUT_DIR/$KIT_NAME"

rm -rf "$TMP_DIR"
mkdir -p "$TMP_DIR"

cp -R "$ROOT_DIR/adapter-start-kit/." "$TMP_DIR/"
cp -R "$ROOT_DIR/adapter_service" "$TMP_DIR/"
cp -R "$ROOT_DIR/config" "$TMP_DIR/"
cp -R "$ROOT_DIR/templates" "$TMP_DIR/"
find "$TMP_DIR" \( -name '.DS_Store' -o -name '._*' -o -name '__pycache__' \) -exec rm -rf {} +

COPYFILE_DISABLE=1 tar -czf "$OUT_DIR/$KIT_NAME.tar.gz" -C "$OUT_DIR" "$KIT_NAME"

echo "Adapter start kit created at $OUT_DIR/$KIT_NAME.tar.gz"
