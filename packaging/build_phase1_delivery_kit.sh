#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${1:-$ROOT_DIR/dist-phase1-delivery-kit}"
DATE_TAG="$(date '+%Y%m%d')"
KIT_NAME="ai-wps-phase1-delivery-${DATE_TAG}"
TMP_DIR="$OUT_DIR/$KIT_NAME"

FORMAL_SRC="$ROOT_DIR/formal-plugin-kit/wps-ai-assistant_1.0.0"
ADAPTER_SRC="$ROOT_DIR/adapter-start-kit"
PIP_TAR="$ROOT_DIR/dist-offline-deps/kylin-v10-arm-py38-pip-bootstrap-20260506.tar.gz"
RUNTIME_TAR="$ROOT_DIR/dist-offline-deps/kylin-v10-arm-py38-runtime-deps-20260506.tar.gz"

rm -rf "$TMP_DIR"
mkdir -p "$TMP_DIR/packages/adapter-start-kit" "$TMP_DIR/docs" "$TMP_DIR/installer" "$TMP_DIR/scripts" "$TMP_DIR/wps-jsaddons"

cp -R "$ROOT_DIR/phase1-delivery-kit/." "$TMP_DIR/"
cp -R "$FORMAL_SRC" "$TMP_DIR/packages/wps-ai-assistant_1.0.0"
cp -R "$ADAPTER_SRC/." "$TMP_DIR/packages/adapter-start-kit/"
cp -R "$ROOT_DIR/adapter_service" "$TMP_DIR/packages/adapter-start-kit/"
cp -R "$ROOT_DIR/config" "$TMP_DIR/packages/adapter-start-kit/"
cp -R "$ROOT_DIR/templates" "$TMP_DIR/packages/adapter-start-kit/"
mkdir -p "$TMP_DIR/docs/operations"
cp "$ROOT_DIR/docs/operations/dify-single-workflow-task-routing.md" "$TMP_DIR/docs/operations/"
cp "$ROOT_DIR/docs/operations/phase1-v0.9.0-deployment.md" "$TMP_DIR/docs/operations/"

tar -xzf "$PIP_TAR" -C "$TMP_DIR/packages"
mv "$TMP_DIR/packages/kylin-v10-arm-py38-pip-bootstrap-20260506" "$TMP_DIR/packages/kylin-v10-arm-py38-pip-bootstrap"

tar -xzf "$RUNTIME_TAR" -C "$TMP_DIR/packages"

find "$TMP_DIR" \( -name '.DS_Store' -o -name '._*' -o -name '__pycache__' \) -exec rm -rf {} +
find "$TMP_DIR" -type f -name '*.sh' -exec chmod 755 {} \;
find "$TMP_DIR/packages/adapter-start-kit/adapter_service" -type f -name '*.py' -exec chmod 755 {} \;

COPYFILE_DISABLE=1 tar -czf "$OUT_DIR/$KIT_NAME.tar.gz" -C "$OUT_DIR" "$KIT_NAME"

echo "Phase1 delivery kit created at $OUT_DIR/$KIT_NAME.tar.gz"
