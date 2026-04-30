#!/usr/bin/env bash
set -euo pipefail

KIT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="${1:-local}"

chmod_cmd="chmod"
if [[ "$MODE" == "sudo" ]]; then
  chmod_cmd="sudo chmod"
fi

echo "permission_mode=$MODE"
echo "target_root=$KIT_ROOT"

find "$KIT_ROOT/scripts" -type f -name '*.sh' -print0 | while IFS= read -r -d '' file; do
  $chmod_cmd +x "$file"
  echo "exec_enabled=$file"
done

find "$KIT_ROOT/adapter_service" -type f -name '*.py' -print0 | while IFS= read -r -d '' file; do
  $chmod_cmd +x "$file"
  echo "exec_enabled=$file"
done

echo "exec_permissions=done"
