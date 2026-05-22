#!/usr/bin/env bash
set -euo pipefail

echo "date=$(date '+%Y-%m-%d %H:%M:%S %z')"
echo "kernel=$(uname -sr)"
echo "machine=$(uname -m)"

if command -v python3 >/dev/null 2>&1; then
  echo "python3_path=$(command -v python3)"
  echo "python3_version=$(python3 --version 2>&1)"
  if python3 -c "import uvicorn, fastapi" >/dev/null 2>&1; then
    echo "uvicorn_runtime=ready"
  else
    echo "uvicorn_runtime=missing"
    echo "uvicorn_runtime_hint=安装 packages/kylin-v10-arm-py38 离线运行依赖后再启动 adapter"
  fi
else
  echo "python3_path=missing"
  echo "python3_version=missing"
  echo "uvicorn_runtime=missing"
fi

if command -v curl >/dev/null 2>&1; then
  echo "curl_path=$(command -v curl)"
else
  echo "curl_path=missing"
fi
