#!/usr/bin/env bash
set -euo pipefail

KIT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_FILE="$KIT_ROOT/logs/adapter.log"
LINES="${1:-80}"

if [ ! -f "$LOG_FILE" ]; then
  echo "log_missing path=$LOG_FILE"
  echo "next_step=bash scripts/status_adapter.sh"
  exit 1
fi

echo "adapter_log_path=$LOG_FILE"
echo "adapter_log_tail_lines=$LINES"
tail -n "$LINES" "$LOG_FILE"

if tail -n "$LINES" "$LOG_FILE" | grep -q "provider=mock"; then
  echo
  echo "provider_mock_detected=true"
  echo "hint=provider=mock 表示 adapter 未向企业 Dify 转发；先执行 bash scripts/check_health.sh，确认 provider_configured=true。"
  echo "hint_debug=配置完成后重新执行任务，再访问 /provider/debug-last 查看真实转发请求摘要。"
fi
