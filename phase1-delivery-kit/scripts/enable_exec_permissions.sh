#!/usr/bin/env bash
set -euo pipefail

DELIVERY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

find "$DELIVERY_ROOT" -type f -name '*.sh' -exec chmod +x {} \;
if [ -d "$DELIVERY_ROOT/packages/adapter-start-kit/scripts" ]; then
  find "$DELIVERY_ROOT/packages/adapter-start-kit/scripts" -type f -name '*.sh' -exec chmod +x {} \;
fi
if [ -d "$DELIVERY_ROOT/packages/adapter-start-kit/adapter_service" ]; then
  find "$DELIVERY_ROOT/packages/adapter-start-kit/adapter_service" -type f -name '*.py' -exec chmod +x {} \;
fi

echo "exec_permissions=done root=$DELIVERY_ROOT"
