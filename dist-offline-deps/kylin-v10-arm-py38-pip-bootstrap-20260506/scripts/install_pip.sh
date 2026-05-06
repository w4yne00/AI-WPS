#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "python_not_found=$PYTHON_BIN"
  echo "请设置 PYTHON_BIN=/usr/bin/python3.8 后重试。"
  exit 1
fi

echo "python=$($PYTHON_BIN --version 2>&1)"

if "$PYTHON_BIN" -m pip --version >/dev/null 2>&1; then
  echo "pip_already_available=$($PYTHON_BIN -m pip --version 2>&1)"
  exit 0
fi

echo "pip_missing=true"
echo "install_method=get-pip-offline"
"$PYTHON_BIN" "$ROOT_DIR/get-pip.py" \
  --no-index \
  --find-links "$ROOT_DIR/wheels" \
  pip==24.0 setuptools==69.5.1 wheel==0.43.0

echo "pip_installed=$($PYTHON_BIN -m pip --version 2>&1)"
