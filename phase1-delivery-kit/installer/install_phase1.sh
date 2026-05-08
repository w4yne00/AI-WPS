#!/usr/bin/env bash
set -euo pipefail

DELIVERY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
PORT="${PORT:-18100}"
WPS_JSADDONS_DIR="${WPS_JSADDONS_DIR:-/home/cloud/.local/share/Kingsoft/wps/jsaddons}"
INSTALL_ROOT="${AI_WPS_INSTALL_ROOT:-$HOME/ai-wps-phase1}"

PLUGIN_NAME="wps-ai-assistant_1.0.0"
PLUGIN_SOURCE="$DELIVERY_ROOT/packages/$PLUGIN_NAME"
ADAPTER_SOURCE="$DELIVERY_ROOT/packages/adapter-start-kit"
PIP_BOOTSTRAP_DIR="$DELIVERY_ROOT/packages/kylin-v10-arm-py38-pip-bootstrap"
RUNTIME_DEPS_DIR="$DELIVERY_ROOT/packages/kylin-v10-arm-py38"
PUBLISH_SOURCE="$DELIVERY_ROOT/wps-jsaddons/publish.xml"
ADAPTER_TARGET="$INSTALL_ROOT/adapter-start-kit"

log() {
  printf '%s\n' "$*"
}

fail() {
  log "install_failed=$*"
  exit 1
}

copy_dir() {
  local source_dir="$1"
  local target_dir="$2"
  rm -rf "$target_dir"
  mkdir -p "$(dirname "$target_dir")"
  cp -R "$source_dir" "$target_dir"
}

enable_exec_permissions() {
  find "$DELIVERY_ROOT" -type f -name '*.sh' -exec chmod +x {} \;
  if [ -d "$ADAPTER_TARGET/scripts" ]; then
    find "$ADAPTER_TARGET/scripts" -type f -name '*.sh' -exec chmod +x {} \;
  fi
  if [ -d "$ADAPTER_TARGET/adapter_service" ]; then
    find "$ADAPTER_TARGET/adapter_service" -type f -name '*.py' -exec chmod +x {} \;
  fi
}

install_pip_if_needed() {
  if "$PYTHON_BIN" -m pip --version >/dev/null 2>&1; then
    log "pip_status=already_available value=$("$PYTHON_BIN" -m pip --version 2>&1)"
    return
  fi

  [ -f "$PIP_BOOTSTRAP_DIR/get-pip.py" ] || fail "pip_bootstrap_missing"
  log "pip_status=missing action=offline_bootstrap"
  if "$PYTHON_BIN" "$PIP_BOOTSTRAP_DIR/get-pip.py" \
    --no-index \
    --find-links "$PIP_BOOTSTRAP_DIR/wheels" \
    pip==24.0 setuptools==69.5.1 wheel==0.43.0; then
    log "pip_status=installed_system_or_default"
  else
    log "pip_install_default_failed=true action=retry_user_site"
    "$PYTHON_BIN" "$PIP_BOOTSTRAP_DIR/get-pip.py" \
      --user \
      --no-index \
      --find-links "$PIP_BOOTSTRAP_DIR/wheels" \
      pip==24.0 setuptools==69.5.1 wheel==0.43.0
    log "pip_status=installed_user_site"
  fi

  "$PYTHON_BIN" -m pip --version
}

install_runtime_deps() {
  [ -d "$RUNTIME_DEPS_DIR/wheels" ] || fail "runtime_wheels_missing"
  log "runtime_deps=installing"
  if "$PYTHON_BIN" -m pip install \
    --no-index \
    --find-links "$RUNTIME_DEPS_DIR/wheels" \
    -r "$RUNTIME_DEPS_DIR/requirements-runtime.txt"; then
    log "runtime_deps=installed_system_or_default"
  else
    log "runtime_deps_default_failed=true action=retry_user_site"
    "$PYTHON_BIN" -m pip install \
      --user \
      --no-index \
      --find-links "$RUNTIME_DEPS_DIR/wheels" \
      -r "$RUNTIME_DEPS_DIR/requirements-runtime.txt"
    log "runtime_deps=installed_user_site"
  fi

  "$PYTHON_BIN" -c "import fastapi, uvicorn, pydantic, requests; print('runtime_deps_ok')"
}

install_wps_plugin() {
  [ -d "$PLUGIN_SOURCE" ] || fail "plugin_source_missing"
  [ -f "$PUBLISH_SOURCE" ] || fail "publish_xml_missing"

  mkdir -p "$WPS_JSADDONS_DIR"
  copy_dir "$PLUGIN_SOURCE" "$WPS_JSADDONS_DIR/$PLUGIN_NAME"

  if [ -f "$WPS_JSADDONS_DIR/publish.xml" ]; then
    cp "$WPS_JSADDONS_DIR/publish.xml" "$WPS_JSADDONS_DIR/publish.xml.bak.$(date '+%Y%m%d%H%M%S')"
    {
      printf '%s\n' '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
      printf '%s\n' '<jsplugins>'
      printf '%s\n' '  <jsplugin name="wps-ai-assistant" url="file://" type="wps" enable="enable_dev" version="1.0.0"/>'
      grep '<jsplugin ' "$WPS_JSADDONS_DIR/publish.xml" | grep -v 'name="wps-ai-assistant"' || true
      printf '%s\n' '</jsplugins>'
    } > "$WPS_JSADDONS_DIR/publish.xml.tmp"
    mv "$WPS_JSADDONS_DIR/publish.xml.tmp" "$WPS_JSADDONS_DIR/publish.xml"
  else
    cp "$PUBLISH_SOURCE" "$WPS_JSADDONS_DIR/publish.xml"
  fi

  log "wps_plugin_installed=$WPS_JSADDONS_DIR/$PLUGIN_NAME"
  log "publish_xml_installed=$WPS_JSADDONS_DIR/publish.xml"
}

install_adapter() {
  [ -d "$ADAPTER_SOURCE" ] || fail "adapter_source_missing"
  mkdir -p "$INSTALL_ROOT"
  copy_dir "$ADAPTER_SOURCE" "$ADAPTER_TARGET"
  enable_exec_permissions
  log "adapter_installed=$ADAPTER_TARGET"
}

start_and_check_adapter() {
  log "adapter_start=uvicorn port=$PORT"
  bash "$ADAPTER_TARGET/scripts/start_uvicorn_adapter.sh" "$PORT"
  bash "$ADAPTER_TARGET/scripts/check_health.sh" "$PORT"
}

log "phase1_install_start=true"
log "delivery_root=$DELIVERY_ROOT"
log "python=$($PYTHON_BIN --version 2>&1)"
log "wps_jsaddons_dir=$WPS_JSADDONS_DIR"
log "install_root=$INSTALL_ROOT"

enable_exec_permissions
install_pip_if_needed
install_runtime_deps
install_wps_plugin
install_adapter
start_and_check_adapter

log "phase1_install_done=true"
log "next_step=restart WPS, open WPS AI 助理 tab, then run scripts/phase1_smoke_test.sh"
