#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="${SERVICE_NAME:-ai-wps-adapter.service}"
SERVICE_FILE="/etc/systemd/system/$SERVICE_NAME"

if [ "$(id -u)" -ne 0 ]; then
  echo "autostart_uninstall_requires_sudo=true"
  exec sudo env SERVICE_NAME="$SERVICE_NAME" bash "$0"
fi

if ! command -v systemctl >/dev/null 2>&1; then
  echo "autostart_uninstall_failed=systemctl_not_found"
  exit 1
fi

systemctl disable --now "$SERVICE_NAME" >/dev/null 2>&1 || true

if [ -f "$SERVICE_FILE" ]; then
  rm -f "$SERVICE_FILE"
  echo "service_file_removed=$SERVICE_FILE"
else
  echo "service_file_missing=$SERVICE_FILE"
fi

systemctl daemon-reload
systemctl reset-failed "$SERVICE_NAME" >/dev/null 2>&1 || true

echo "autostart_uninstalled=true"
echo "service_name=$SERVICE_NAME"
