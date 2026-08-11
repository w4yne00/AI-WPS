#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${1:-}"
RUNTIME_DEPS_DIR="${2:-}"
PIP_BOOTSTRAP_DIR="${3:-}"
PRIVATE_RUNTIME_DIR="${4:-}"

log() {
  printf '%s\n' "$*"
}

fail() {
  log "private_runtime_failed=$*"
  exit 1
}

verify_manifest_paths() {
  local root="$1"
  local manifest="$root/SHA256SUMS"
  local digest relative
  [ -s "$manifest" ] || fail "offline_hash_manifest_missing path=$manifest"
  while read -r digest relative; do
    [ -n "${digest:-}" ] || continue
    relative="${relative#\*}"
    case "$relative" in
      /*|../*|*/../*) fail "offline_hash_path_rejected path=$relative" ;;
    esac
    case "$digest" in
      *[!0-9a-fA-F]*|'') fail "offline_hash_manifest_invalid path=$manifest" ;;
    esac
    [ "${#digest}" -eq 64 ] || fail "offline_hash_manifest_invalid path=$manifest"
    [ -f "$root/$relative" ] || fail "offline_hash_file_missing path=$relative"
  done < "$manifest"
}

verify_hashes() {
  local root="$1"
  verify_manifest_paths "$root"
  if command -v sha256sum >/dev/null 2>&1; then
    (cd "$root" && sha256sum -c SHA256SUMS >/dev/null 2>&1) || \
      fail "offline_hash_verification_failed path=$root"
    return
  fi
  if command -v shasum >/dev/null 2>&1; then
    (cd "$root" && shasum -a 256 -c SHA256SUMS >/dev/null 2>&1) || \
      fail "offline_hash_verification_failed path=$root"
    return
  fi
  fail "sha256_tool_missing"
}

validate_lock_file() {
  local lock_file="$1"
  [ -s "$lock_file" ] || fail "runtime_lock_missing path=$lock_file"
  if PYTHONNOUSERSITE=1 PYTHONPATH="" "$PYTHON_BIN" -s - "$lock_file" <<'PY'
import re
import sys

pattern = re.compile(
    r"^[A-Za-z0-9_.-]+==\S+\s+--hash=sha256:[0-9a-f]{64}"
    r"(?:\s+--hash=sha256:[0-9a-f]{64})*\s*$"
)
with open(sys.argv[1], encoding="utf-8") as handle:
    for raw_line in handle:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if pattern.fullmatch(line) is None:
            raise SystemExit(1)
PY
  then
    return
  fi
  fail "runtime_lock_not_fully_pinned path=$lock_file"
}

[ -n "$PYTHON_BIN" ] || fail "python_argument_required"
[ -x "$PYTHON_BIN" ] || fail "python_not_executable path=$PYTHON_BIN"
[ -d "$RUNTIME_DEPS_DIR/wheels" ] || fail "runtime_wheels_missing"
[ -d "$PIP_BOOTSTRAP_DIR/wheels" ] || fail "pip_bootstrap_wheels_missing"
[ -n "$PRIVATE_RUNTIME_DIR" ] || fail "private_runtime_target_required"
case "$PRIVATE_RUNTIME_DIR" in
  /*) ;;
  *) fail "private_runtime_target_must_be_absolute" ;;
esac

verify_hashes "$RUNTIME_DEPS_DIR"
verify_hashes "$PIP_BOOTSTRAP_DIR"
validate_lock_file "$RUNTIME_DEPS_DIR/requirements-lock.txt"

if [ -e "$PRIVATE_RUNTIME_DIR" ]; then
  fail "private_runtime_target_exists path=$PRIVATE_RUNTIME_DIR"
fi
mkdir -p "$PRIVATE_RUNTIME_DIR"

PIP_MODULE_PATH=""
if ! PYTHONNOUSERSITE=1 PYTHONPATH="" "$PYTHON_BIN" -s -m pip --version >/dev/null 2>&1; then
  [ -f "$PIP_BOOTSTRAP_DIR/get-pip.py" ] || fail "pip_bootstrap_missing"
  PIP_MODULE_PATH="$PRIVATE_RUNTIME_DIR/.pip-bootstrap"
  mkdir -p "$PIP_MODULE_PATH"
  PYTHONNOUSERSITE=1 PYTHONPATH="" "$PYTHON_BIN" -s \
    "$PIP_BOOTSTRAP_DIR/get-pip.py" \
    --no-index \
    --find-links "$PIP_BOOTSTRAP_DIR/wheels" \
    --target "$PIP_MODULE_PATH" \
    pip==24.0 setuptools==69.5.1 wheel==0.43.0
fi

PYTHONNOUSERSITE=1 PYTHONPATH="$PIP_MODULE_PATH" "$PYTHON_BIN" -s -m pip install \
  --disable-pip-version-check \
  --no-index \
  --no-deps \
  --require-hashes \
  --find-links "$RUNTIME_DEPS_DIR/wheels" \
  --target "$PRIVATE_RUNTIME_DIR" \
  -r "$RUNTIME_DEPS_DIR/requirements-lock.txt"

cp "$RUNTIME_DEPS_DIR/requirements-lock.txt" "$PRIVATE_RUNTIME_DIR/requirements-lock.txt"
PYTHONNOUSERSITE=1 PYTHONPATH="$PRIVATE_RUNTIME_DIR" "$PYTHON_BIN" -s -c \
  "import os, fastapi, pydantic, requests, uvicorn; root=os.path.realpath(r'$PRIVATE_RUNTIME_DIR'); paths=[os.path.realpath(module.__file__) for module in (fastapi, pydantic, requests, uvicorn)]; assert all(os.path.commonpath([root, path]) == root for path in paths)"

log "private_runtime=ready path=$PRIVATE_RUNTIME_DIR"
