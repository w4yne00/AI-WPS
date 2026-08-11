#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${1:-}"
CANDIDATE_ROOT="${2:-}"
PRIVATE_RUNTIME_DIR="${3:-}"
CANDIDATE_PORT="${4:-}"
EXPECTED_VERSION="${5:-}"
PREFLIGHT_ROOT="${6:-}"
CANDIDATE_PID=""

log() {
  printf '%s\n' "$*"
}

fail() {
  log "candidate_preflight_failed=$*"
  exit 1
}

json_response_field() {
  local field="$1"
  "$PYTHON_BIN" -c '
import json
import sys

payload = json.load(sys.stdin)
data = payload.get("data", payload) if isinstance(payload, dict) else {}
value = data.get(sys.argv[1], "") if isinstance(data, dict) else ""
print(value if isinstance(value, str) else "")
' "$field" candidate-status
}

stop_candidate() {
  if [ -n "$CANDIDATE_PID" ] && kill -0 "$CANDIDATE_PID" >/dev/null 2>&1; then
    kill "$CANDIDATE_PID" >/dev/null 2>&1 || true
    wait "$CANDIDATE_PID" 2>/dev/null || true
  fi
}
trap stop_candidate EXIT

[ -x "$PYTHON_BIN" ] || fail "python_not_executable"
[ -d "$CANDIDATE_ROOT/adapter_service" ] || fail "candidate_adapter_missing"
[ -d "$PRIVATE_RUNTIME_DIR" ] || fail "private_runtime_missing"
case "$CANDIDATE_PORT" in
  ''|*[!0-9]*) fail "isolated_port_invalid" ;;
esac
[ "$CANDIDATE_PORT" -ge 1 ] && [ "$CANDIDATE_PORT" -le 65535 ] || fail "isolated_port_invalid"
[ -n "$EXPECTED_VERSION" ] || fail "expected_version_required"
case "$PREFLIGHT_ROOT" in
  /*) ;;
  *) fail "preflight_root_must_be_absolute" ;;
esac
command -v curl >/dev/null 2>&1 || fail "curl_missing"

BASE_URL="http://127.0.0.1:$CANDIDATE_PORT"
if curl -fsS "$BASE_URL/health/live" >/dev/null 2>&1; then
  fail "isolated_port_in_use port=$CANDIDATE_PORT"
fi

mkdir -p \
  "$PREFLIGHT_ROOT/state" \
  "$PREFLIGHT_ROOT/backups" \
  "$PREFLIGHT_ROOT/var/logs" \
  "$PREFLIGHT_ROOT/var/run" \
  "$PREFLIGHT_ROOT/var/transactions"
chmod 700 \
  "$PREFLIGHT_ROOT/state" \
  "$PREFLIGHT_ROOT/backups" \
  "$PREFLIGHT_ROOT/var" \
  "$PREFLIGHT_ROOT/var/logs" \
  "$PREFLIGHT_ROOT/var/run" \
  "$PREFLIGHT_ROOT/var/transactions"

PREFLIGHT_STATE_SOURCE="${AI_WPS_PREFLIGHT_STATE_SOURCE:-}"
if [ -n "$PREFLIGHT_STATE_SOURCE" ]; then
  case "$PREFLIGHT_STATE_SOURCE" in
    /*) ;;
    *) fail "preflight_state_source_must_be_absolute" ;;
  esac
  [ -d "$PREFLIGHT_STATE_SOURCE" ] || fail "preflight_state_source_missing"
  [ ! -L "$PREFLIGHT_STATE_SOURCE" ] || fail "preflight_state_source_symlink_rejected"
  cp -R "$PREFLIGHT_STATE_SOURCE/." "$PREFLIGHT_ROOT/state/"
  find "$PREFLIGHT_ROOT/state" -type d -exec chmod 700 {} \;
  find "$PREFLIGHT_ROOT/state" -type f -exec chmod 600 {} \;
fi

cd "$CANDIDATE_ROOT/adapter_service"
AI_WPS_STATE_DIR="$PREFLIGHT_ROOT/state" \
AI_WPS_BACKUP_DIR="$PREFLIGHT_ROOT/backups" \
AI_WPS_VAR_DIR="$PREFLIGHT_ROOT/var" \
PYTHONNOUSERSITE=1 \
PYTHONPATH="$PRIVATE_RUNTIME_DIR" \
  "$PYTHON_BIN" -s -c "import app.main, fastapi, pydantic, requests, uvicorn" \
  || fail "candidate_full_import_failed"

AI_WPS_STATE_DIR="$PREFLIGHT_ROOT/state" \
AI_WPS_BACKUP_DIR="$PREFLIGHT_ROOT/backups" \
AI_WPS_VAR_DIR="$PREFLIGHT_ROOT/var" \
PYTHONNOUSERSITE=1 \
PYTHONPATH="$PRIVATE_RUNTIME_DIR" \
  "$PYTHON_BIN" -s -m uvicorn app.main:app \
    --host 127.0.0.1 \
    --port "$CANDIDATE_PORT" \
    > "$PREFLIGHT_ROOT/var/logs/candidate.log" 2>&1 &
CANDIDATE_PID=$!

LIVE_BODY=""
for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
  LIVE_BODY="$(curl -fsS "$BASE_URL/health/live" 2>/dev/null || true)"
  [ -n "$LIVE_BODY" ] && break
  if ! kill -0 "$CANDIDATE_PID" >/dev/null 2>&1; then
    fail "candidate_start_failed"
  fi
  sleep 1
done
[ -n "$LIVE_BODY" ] || fail "candidate_live_timeout"

READY_BODY="$(curl -sS "$BASE_URL/health/ready" 2>/dev/null || true)"
[ -n "$READY_BODY" ] || fail "candidate_business_not_ready"
HEALTH_BODY="$(curl -sS "$BASE_URL/health" 2>/dev/null || true)"
[ -n "$HEALTH_BODY" ] || fail "candidate_health_unreachable"

LIVE_STATUS="$(printf '%s' "$LIVE_BODY" | json_response_field status)" \
  || fail "candidate_live_contract_invalid"
READY_STATUS="$(printf '%s' "$READY_BODY" | json_response_field status)" \
  || fail "candidate_ready_contract_invalid"
HEALTH_STATUS="$(printf '%s' "$HEALTH_BODY" | json_response_field status)" \
  || fail "candidate_health_contract_invalid"
HEALTH_VERSION="$(printf '%s' "$HEALTH_BODY" | json_response_field version)" \
  || fail "candidate_health_contract_invalid"
[ "$LIVE_STATUS" = "live" ] || fail "candidate_live_contract_invalid"
[ "$HEALTH_VERSION" = "$EXPECTED_VERSION" ] \
  || fail "candidate_version_mismatch expected=$EXPECTED_VERSION"

CANDIDATE_STATUS=""
case "$HEALTH_STATUS:$READY_STATUS" in
  recovery:recovery)
    CANDIDATE_STATUS="recovery"
    ;;
  ready:ready)
    CANDIDATE_STATUS="ready"
    ;;
  degraded:degraded)
    CANDIDATE_STATUS="degraded"
    ;;
  *)
    fail "candidate_business_not_ready"
    ;;
esac

RECOVERY_FAULT_SUMMARY=""
if [ "$CANDIDATE_STATUS" = "recovery" ]; then
  RECOVERY_FAULT_SUMMARY="$(
    printf '%s' "$HEALTH_BODY" \
      | "$PYTHON_BIN" -c '
import json
import re
import sys

safe = re.compile(r"^[A-Za-z0-9_.-]{1,96}$")
payload = json.load(sys.stdin)
data = payload.get("data", payload) if isinstance(payload, dict) else {}
subsystems = data.get("subsystems", {}) if isinstance(data, dict) else {}
parts = []
for name in ("modelConfigurations", "taskRoutes", "writingPolicies"):
    item = subsystems.get(name, {}) if isinstance(subsystems, dict) else {}
    if not isinstance(item, dict):
        continue
    status = str(item.get("status", ""))
    if status == "ready":
        continue
    code = str(item.get("errorCode", "unknown")) or "unknown"
    stage = str(item.get("stage", "unknown")) or "unknown"
    if not safe.fullmatch(status) or not safe.fullmatch(code) or not safe.fullmatch(stage):
        continue
    parts.append(":".join((name, status, code, stage)))
print(",".join(parts))
' candidate-recovery-summary
  )" || fail "candidate_recovery_summary_invalid"
  [ -n "$RECOVERY_FAULT_SUMMARY" ] || fail "candidate_recovery_summary_missing"
fi

stop_candidate
CANDIDATE_PID=""
log "candidate_preflight=$CANDIDATE_STATUS version=$EXPECTED_VERSION port=$CANDIDATE_PORT dependencies=$PRIVATE_RUNTIME_DIR"
if [ -n "$RECOVERY_FAULT_SUMMARY" ]; then
  log "candidate_recovery_fault_summary=$RECOVERY_FAULT_SUMMARY"
fi
trap - EXIT
