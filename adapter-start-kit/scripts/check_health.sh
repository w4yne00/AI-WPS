#!/usr/bin/env bash
set -euo pipefail

PORT="${1:-18100}"

if ! command -v curl >/dev/null 2>&1; then
  echo "curl_missing"
  exit 1
fi

curl -fsS "http://127.0.0.1:${PORT}/health"
