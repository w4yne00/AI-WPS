#!/usr/bin/env bash
set -euo pipefail

DELIVERY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
PORT="${PORT:-18100}"
WPS_JSADDONS_DIR="${WPS_JSADDONS_DIR:-/home/cloud/.local/share/Kingsoft/wps/jsaddons}"
INSTALL_ROOT="${AI_WPS_INSTALL_ROOT:-$HOME/ai-wps-phase1}"
PLUGIN_DIR="$WPS_JSADDONS_DIR/wps-ai-assistant_1.0.0"
EXCEL_PLUGIN_DIR="$WPS_JSADDONS_DIR/wps-ai-assistant-et_1.0.0"
ADAPTER_DIR="$INSTALL_ROOT/adapter-start-kit"

http_get() {
  local url="$1"
  if command -v curl >/dev/null 2>&1; then
    curl -fsS "$url"
  else
    "$PYTHON_BIN" - "$url" <<'PY'
import sys
from urllib.request import urlopen
print(urlopen(sys.argv[1], timeout=5).read().decode("utf-8"))
PY
  fi
}

echo "phase1_smoke_start=true"
echo "python=$($PYTHON_BIN --version 2>&1)"

if [ -d "$PLUGIN_DIR" ]; then
  echo "wps_plugin_dir=ok path=$PLUGIN_DIR"
else
  echo "wps_plugin_dir=missing path=$PLUGIN_DIR"
  exit 1
fi

if [ -d "$EXCEL_PLUGIN_DIR" ]; then
  echo "et_plugin_dir=ok path=$EXCEL_PLUGIN_DIR"
else
  echo "et_plugin_dir=missing path=$EXCEL_PLUGIN_DIR"
  exit 1
fi

if [ -f "$WPS_JSADDONS_DIR/publish.xml" ] \
  && grep -q 'name="wps-ai-assistant"' "$WPS_JSADDONS_DIR/publish.xml" \
  && grep -q 'type="wps"' "$WPS_JSADDONS_DIR/publish.xml" \
  && grep -q 'name="wps-ai-assistant-et"' "$WPS_JSADDONS_DIR/publish.xml" \
  && grep -q 'type="et"' "$WPS_JSADDONS_DIR/publish.xml"; then
  echo "publish_xml=ok path=$WPS_JSADDONS_DIR/publish.xml"
else
  echo "publish_xml=missing_or_invalid path=$WPS_JSADDONS_DIR/publish.xml"
  exit 1
fi

"$PYTHON_BIN" -c "import fastapi, uvicorn, pydantic, requests; print('runtime_deps_ok')"

if [ -x "$ADAPTER_DIR/scripts/check_health.sh" ]; then
  bash "$ADAPTER_DIR/scripts/check_health.sh" "$PORT"
else
  echo "adapter_check_script=missing path=$ADAPTER_DIR/scripts/check_health.sh"
  exit 1
fi

echo "templates_response_begin"
http_get "http://127.0.0.1:${PORT}/templates"
echo
echo "templates_response_end"

echo "phase1_smoke_done=true"
