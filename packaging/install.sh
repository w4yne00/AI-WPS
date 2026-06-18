#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_DIR="${1:-$HOME/.wps-ai-assistant}"
CONFIG_BACKUP=""

mkdir -p "$TARGET_DIR"
mkdir -p "$TARGET_DIR/logs"

preserve_runtime_config() {
  [ -d "$TARGET_DIR" ] || return 0
  CONFIG_BACKUP="$(mktemp -d "${TMPDIR:-/tmp}/ai-wps-config.XXXXXX")"
  mkdir -p "$CONFIG_BACKUP/config" "$CONFIG_BACKUP/run"
  if [ -f "$TARGET_DIR/config/adapter.json" ]; then
    cp "$TARGET_DIR/config/adapter.json" "$CONFIG_BACKUP/config/adapter.json"
  fi
  if [ -f "$TARGET_DIR/run/provider_api_key" ]; then
    cp "$TARGET_DIR/run/provider_api_key" "$CONFIG_BACKUP/run/provider_api_key"
  fi
  if [ -d "$TARGET_DIR/run/provider_api_keys" ]; then
    cp -R "$TARGET_DIR/run/provider_api_keys" "$CONFIG_BACKUP/run/provider_api_keys"
  fi
}

restore_runtime_config() {
  [ -n "$CONFIG_BACKUP" ] || return 0
  [ -d "$CONFIG_BACKUP" ] || return 0
  if [ -f "$CONFIG_BACKUP/config/adapter.json" ]; then
    mkdir -p "$TARGET_DIR/config"
    cp "$CONFIG_BACKUP/config/adapter.json" "$TARGET_DIR/config/adapter.json"
  fi
  if [ -f "$CONFIG_BACKUP/run/provider_api_key" ]; then
    mkdir -p "$TARGET_DIR/run"
    cp "$CONFIG_BACKUP/run/provider_api_key" "$TARGET_DIR/run/provider_api_key"
  fi
  if [ -d "$CONFIG_BACKUP/run/provider_api_keys" ]; then
    mkdir -p "$TARGET_DIR/run"
    rm -rf "$TARGET_DIR/run/provider_api_keys"
    cp -R "$CONFIG_BACKUP/run/provider_api_keys" "$TARGET_DIR/run/provider_api_keys"
  fi
  rm -rf "$CONFIG_BACKUP"
}

preserve_runtime_config
cp -R "$ROOT_DIR/adapter_service" "$TARGET_DIR/"
cp -R "$ROOT_DIR/wps-addon" "$TARGET_DIR/"
cp -R "$ROOT_DIR/templates" "$TARGET_DIR/"
cp -R "$ROOT_DIR/config" "$TARGET_DIR/"
restore_runtime_config

echo "Installed WPS AI Assistant files into: $TARGET_DIR"
