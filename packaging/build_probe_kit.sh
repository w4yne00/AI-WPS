#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${1:-$ROOT_DIR/dist-probe-kit}"
KIT_NAME="wps-runtime-probe-kit-$(date '+%Y%m%d')"
TMP_DIR="$OUT_DIR/$KIT_NAME"
PLUGIN_DIR_NAME="wps-probe-addon_1.0.0"

rm -rf "$TMP_DIR"
mkdir -p "$TMP_DIR"

cp -R "$ROOT_DIR/probe-kit/." "$TMP_DIR/"
mv "$TMP_DIR/wps-probe-addon" "$TMP_DIR/$PLUGIN_DIR_NAME"
find "$TMP_DIR" \( -name '.DS_Store' -o -name '._*' \) -delete

COPYFILE_DISABLE=1 tar -czf "$OUT_DIR/$KIT_NAME.tar.gz" -C "$OUT_DIR" "$KIT_NAME"

echo "Probe kit created at $OUT_DIR/$KIT_NAME.tar.gz"
