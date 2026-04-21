#!/usr/bin/env bash
set -euo pipefail

TARGET_DIR="${1:-$HOME/.wps-ai-assistant}"

if [[ -d "$TARGET_DIR" ]]; then
  rm -rf "$TARGET_DIR"
  echo "Removed $TARGET_DIR"
else
  echo "Nothing to remove at $TARGET_DIR"
fi
