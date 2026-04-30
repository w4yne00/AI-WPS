#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

"$PYTHON_BIN" -m pip install \
  --no-index \
  --find-links "$SCRIPT_DIR/wheels" \
  -r "$SCRIPT_DIR/requirements-runtime.txt"

"$PYTHON_BIN" -c "import fastapi, uvicorn, pydantic, requests; print('runtime_deps_ok')"
