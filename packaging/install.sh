#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_DIR="${1:-$HOME/.wps-ai-assistant}"

mkdir -p "$TARGET_DIR"
mkdir -p "$TARGET_DIR/logs"

cp -R "$ROOT_DIR/adapter_service" "$TARGET_DIR/"
cp -R "$ROOT_DIR/wps-addon" "$TARGET_DIR/"
cp -R "$ROOT_DIR/templates" "$TARGET_DIR/"
cp -R "$ROOT_DIR/config" "$TARGET_DIR/"

echo "Installed WPS AI Assistant files into: $TARGET_DIR"
