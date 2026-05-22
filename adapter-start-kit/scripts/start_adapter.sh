#!/usr/bin/env bash
set -euo pipefail

KIT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${1:-18100}"

echo "adapter_start_mode=uvicorn"
echo "adapter_start_entry=scripts/start_uvicorn_adapter.sh"
bash "$KIT_ROOT/scripts/start_uvicorn_adapter.sh" "$PORT"
