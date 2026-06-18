#!/usr/bin/env bash
set -euo pipefail

KIT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${1:-18100}"
SERVICE_USER="${2:-${SUDO_USER:-$(id -un)}}"
SERVICE_NAME="${SERVICE_NAME:-ai-wps-adapter.service}"
SERVICE_FILE="/etc/systemd/system/$SERVICE_NAME"
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3 || true)}"

if [ -z "$PYTHON_BIN" ]; then
  echo "autostart_install_failed=python3_not_found"
  echo "请先确认目标机已安装 Python 3，或使用 PYTHON_BIN=/usr/bin/python3.8 bash scripts/install_autostart.sh $PORT"
  exit 1
fi

if [ "$(id -u)" -ne 0 ]; then
  echo "autostart_install_requires_sudo=true"
  exec sudo env SERVICE_NAME="$SERVICE_NAME" PYTHON_BIN="$PYTHON_BIN" bash "$0" "$PORT" "$SERVICE_USER"
fi

if ! command -v systemctl >/dev/null 2>&1; then
  echo "autostart_install_failed=systemctl_not_found"
  echo "当前系统未检测到 systemd/systemctl，无法安装开机自启动服务。"
  exit 1
fi

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  echo "autostart_install_failed=user_not_found user=$SERVICE_USER"
  echo "请指定真实登录用户：bash scripts/install_autostart.sh $PORT <用户名>"
  exit 1
fi

cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=AI-WPS local adapter
After=network-online.target
Wants=network-online.target

[Service]
Type=forking
User=$SERVICE_USER
WorkingDirectory=$KIT_ROOT
Environment=PYTHON_BIN=$PYTHON_BIN
PIDFile=$KIT_ROOT/run/adapter.pid
ExecStart=/bin/bash $KIT_ROOT/scripts/start_adapter.sh $PORT
ExecStop=/bin/bash $KIT_ROOT/scripts/stop_adapter.sh $PORT
Restart=on-failure
RestartSec=10
TimeoutStartSec=30
TimeoutStopSec=20

[Install]
WantedBy=multi-user.target
EOF

chmod 644 "$SERVICE_FILE"
systemctl daemon-reload
systemctl enable --now "$SERVICE_NAME"

echo "autostart_installed=true"
echo "service_name=$SERVICE_NAME"
echo "service_file=$SERVICE_FILE"
echo "service_user=$SERVICE_USER"
echo "adapter_root=$KIT_ROOT"
echo "adapter_port=$PORT"
echo "python_bin=$PYTHON_BIN"
echo "status_command=systemctl status $SERVICE_NAME --no-pager"
