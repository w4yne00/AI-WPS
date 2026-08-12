#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
PYTHON38_BIN="${PYTHON38_BIN:-python3.8}"
BASELINE_ARCHIVE="${AI_WPS_V0231_BASELINE_ARCHIVE:-}"
OUT_DIR="${1:-$ROOT_DIR/dist-phase1-delivery-kit}"
DATE_TAG="${DATE_TAG:-$(date '+%Y%m%d')}"
VERSION="0.24.0-alpha"
KIT_NAME="ai-wps-phase1-delivery-${DATE_TAG}-v0240"
TMP_DIR="$OUT_DIR/$KIT_NAME"
ARCHIVE_PATH="$OUT_DIR/$KIT_NAME.tar.gz"
PENDING_ARCHIVE_PATH="$OUT_DIR/.$KIT_NAME.pending.tar.gz"
PENDING_CHECKSUM_PATH="$OUT_DIR/.$KIT_NAME.pending.sha256"
SOURCE_ALLOWLIST="$ROOT_DIR/packaging/delivery-sources-v0240.json"
PUBLISHED_ARCHIVE="0"

if [[ ! "$DATE_TAG" =~ ^[0-9]{8}$ ]]; then
  echo "delivery_date_tag_invalid=$DATE_TAG"
  exit 1
fi
if [ -e "$ARCHIVE_PATH" ] || [ -e "$ARCHIVE_PATH.sha256" ]; then
  echo "delivery_output_exists=$ARCHIVE_PATH"
  exit 1
fi
if [ -e "$TMP_DIR" ] || [ -e "$PENDING_ARCHIVE_PATH" ] || [ -e "$PENDING_CHECKSUM_PATH" ]; then
  echo "delivery_temporary_output_exists=$TMP_DIR"
  exit 1
fi
if [ -z "$BASELINE_ARCHIVE" ] || [ ! -f "$BASELINE_ARCHIVE" ]; then
  echo "v0231_baseline_archive_required=true"
  exit 1
fi

cleanup_failed_outputs() {
  if [ -d "$TMP_DIR" ]; then
    rm -rf "$TMP_DIR"
  fi
  rm -f "$PENDING_ARCHIVE_PATH" "$PENDING_CHECKSUM_PATH"
  if [ "$PUBLISHED_ARCHIVE" = "1" ]; then
    rm -f "$ARCHIVE_PATH"
  fi
}
trap cleanup_failed_outputs EXIT
cleanup_failed_outputs
mkdir -p "$OUT_DIR"

"$PYTHON_BIN" "$ROOT_DIR/packaging/assemble_phase1_delivery.py" \
  --repo-root "$ROOT_DIR" \
  --source-allowlist "$SOURCE_ALLOWLIST" \
  --output "$TMP_DIR"

mkdir -p "$TMP_DIR/docs/import-templates"
PYTHONPATH="$ROOT_DIR/adapter_service" "$PYTHON_BIN" - \
  "$TMP_DIR/docs/import-templates" <<'PY'
from pathlib import Path
import sys

from app.services.writing_policy.imports import generate_csv_template, generate_xlsx_template

output_dir = Path(sys.argv[1])
(output_dir / "writing-policies-import-template.csv").write_bytes(generate_csv_template())
(output_dir / "writing-policies-import-template.xlsx").write_bytes(generate_xlsx_template())
PY

"$PYTHON_BIN" "$ROOT_DIR/packaging/prepare_v0240_delivery.py" \
  "$TMP_DIR" --version "$VERSION" --date "$DATE_TAG"

"$PYTHON_BIN" - "$TMP_DIR/packages" <<'PY'
from pathlib import Path
import sys

packages = Path(sys.argv[1])
for package_name in (
    "kylin-v10-arm-py38",
    "kylin-v10-arm-py38-pip-bootstrap",
):
    root = packages / package_name
    manifest = root / "SHA256SUMS"
    retained = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        unused_digest, relative = line.split(None, 1)
        relative = relative.lstrip("*")
        if (root / relative).is_file():
            retained.append(line)
    manifest.write_text("\n".join(retained) + "\n", encoding="utf-8")
PY

"$PYTHON_BIN" "$ROOT_DIR/packaging/check_python38_compatibility.py" \
  "$TMP_DIR/packages/adapter-start-kit/adapter_service" \
  "$TMP_DIR/installer/release_transaction.py" \
  "$TMP_DIR/scripts/check_python38_compatibility.py" \
  "$TMP_DIR/scripts/python38_delivery_runtime_gate.py" \
  "$TMP_DIR/scripts/python38_delivery_lifecycle_gate.py" \
  "$TMP_DIR/scripts/audit_delivery.py"

PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" - "$TMP_DIR" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
manifest = json.loads((root / "release-manifest.json").read_text(encoding="utf-8"))
adapter_service_root = root / "packages/adapter-start-kit/adapter_service"
sys.path.insert(0, str(adapter_service_root))
from app.services.system_prompts import SystemPromptStore
from app.services.writing_policy.packs import load_pack_snapshot

pack_root = adapter_service_root / "writing_policy_packs"
if {item["packId"] for item in load_pack_snapshot(pack_root).public_packs()} != set(manifest["writingPolicyPacks"]):
    raise SystemExit("writing policy pack inventory mismatch")
if len(SystemPromptStore(adapter_service_root / "system_prompts").list_metadata()) != manifest["adapter"]["systemPromptCount"]:
    raise SystemExit("system prompt inventory mismatch")
prompt_manifest = json.loads(
    (adapter_service_root / "system_prompts/manifest.json").read_text(encoding="utf-8")
)
required_stages = {
    "word.document_review.full.chunk",
    "word.document_review.full.chunk.correction",
    "word.document_review.full.aggregate",
    "word.document_review.full.aggregate.correction",
}
if set(prompt_manifest.get("stages", {})) != required_stages:
    raise SystemExit("full review stage inventory mismatch")
for stage in prompt_manifest["stages"].values():
    if not stage.get("schema") or not stage.get("schemaSha256"):
        raise SystemExit("full review schema inventory mismatch")
PY

find "$TMP_DIR" -type f -name '*.sh' -exec chmod 755 {} \;
find "$TMP_DIR/packages/adapter-start-kit/adapter_service" -type f -name '*.py' -exec chmod 755 {} \;

"$PYTHON_BIN" "$ROOT_DIR/packaging/audit_phase1_delivery.py" "$TMP_DIR" --write-hashes

COPYFILE_DISABLE=1 tar -czf "$PENDING_ARCHIVE_PATH" -C "$OUT_DIR" "$KIT_NAME"
"$PYTHON38_BIN" "$ROOT_DIR/packaging/python38_delivery_lifecycle_gate.py" \
  "$PENDING_ARCHIVE_PATH" --expected-version "$VERSION" \
  --baseline-archive "$BASELINE_ARCHIVE"

"$PYTHON_BIN" - "$PENDING_ARCHIVE_PATH" "$PENDING_CHECKSUM_PATH" "$(basename "$ARCHIVE_PATH")" <<'PY'
import hashlib
import sys
from pathlib import Path

archive_path = Path(sys.argv[1])
checksum_path = Path(sys.argv[2])
checksum_path.write_text(
    "{0}  {1}\n".format(
        hashlib.sha256(archive_path.read_bytes()).hexdigest(), sys.argv[3]
    ),
    encoding="utf-8",
)
PY

mv "$PENDING_ARCHIVE_PATH" "$ARCHIVE_PATH"
PUBLISHED_ARCHIVE="1"
mv "$PENDING_CHECKSUM_PATH" "$ARCHIVE_PATH.sha256"
PUBLISHED_ARCHIVE="0"
echo "v0240_delivery_candidate=$ARCHIVE_PATH status=candidate"
trap - EXIT
