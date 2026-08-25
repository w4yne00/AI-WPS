#!/usr/bin/env bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
PYTHON38_BIN="${PYTHON38_BIN:-python3.8}"
BASELINE_ARCHIVE="${AI_WPS_V0251_BASELINE_ARCHIVE:-}"
PREVIOUS_CANDIDATE_ARCHIVE="${AI_WPS_V0252_PREVIOUS_CANDIDATE_ARCHIVE:-${AI_WPS_V0251_BASELINE_ARCHIVE:-}}"
OUT_DIR="${1:-$ROOT_DIR/dist-phase1-delivery-kit}"
DATE_TAG="${DATE_TAG:-$(date '+%Y%m%d')}"
VERSION="0.25.2-alpha"
BASELINE_VERSION="0.25.1-alpha"
HEAD_COMMIT="$(git -C "$ROOT_DIR" rev-parse HEAD)"
SOURCE_COMMIT="${AI_WPS_SOURCE_COMMIT:-$HEAD_COMMIT}"
SOURCE_TAG="${SOURCE_COMMIT:0:7}"
KIT_NAME="ai-wps-phase1-delivery-${DATE_TAG}-${SOURCE_TAG}-v0252"
TMP_DIR="$OUT_DIR/$KIT_NAME"
ARCHIVE_PATH="$OUT_DIR/$KIT_NAME.tar.gz"
PENDING_ARCHIVE_PATH="$OUT_DIR/.$KIT_NAME.pending.tar.gz"
PENDING_CHECKSUM_PATH="$OUT_DIR/.$KIT_NAME.pending.sha256"
SOURCE_ALLOWLIST="$ROOT_DIR/packaging/delivery-sources-v0252.json"
PUBLISHED_ARCHIVE="0"

if [[ ! "$DATE_TAG" =~ ^[0-9]{8}$ ]]; then
  echo "delivery_date_tag_invalid=$DATE_TAG"
  exit 1
fi
if [[ ! "$SOURCE_COMMIT" =~ ^[0-9a-f]{7,40}$ ]]; then
  echo "delivery_source_commit_invalid=$SOURCE_COMMIT"
  exit 1
fi
if [ "$SOURCE_COMMIT" != "$HEAD_COMMIT" ]; then
  echo "delivery_source_commit_not_head=$SOURCE_COMMIT expected=$HEAD_COMMIT"
  exit 1
fi
"$PYTHON_BIN" "$ROOT_DIR/packaging/check_delivery_source_provenance.py" \
  --repo-root "$ROOT_DIR" \
  --source-allowlist "$SOURCE_ALLOWLIST" \
  --source-commit "$SOURCE_COMMIT"
if ! "$PYTHON_BIN" - "$DATE_TAG" <<'PY'
from datetime import datetime
import sys

try:
    datetime.strptime(sys.argv[1], "%Y%m%d")
except ValueError:
    raise SystemExit(1)
PY
then
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
  echo "v0251_baseline_archive_required=true"
  exit 1
fi
if [ -z "$PREVIOUS_CANDIDATE_ARCHIVE" ] || [ ! -f "$PREVIOUS_CANDIDATE_ARCHIVE" ]; then
  echo "v0252_previous_candidate_archive_required=true"
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

"$PYTHON_BIN" "$ROOT_DIR/packaging/prepare_v0252_delivery.py" \
  "$TMP_DIR" \
  --date "$DATE_TAG" \
  --baseline-archive "$BASELINE_ARCHIVE" \
  --previous-candidate-archive "$PREVIOUS_CANDIDATE_ARCHIVE" \
  --baseline-version "$BASELINE_VERSION" \
  --acceptance-issue 59 \
  --source-commit "$SOURCE_COMMIT"

"$PYTHON_BIN" - "$TMP_DIR/packages" <<'PY'
from pathlib import Path
import sys

packages = Path(sys.argv[1])
for package_name in ("kylin-v10-arm-py38", "kylin-v10-arm-py38-pip-bootstrap"):
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

COMPILED_CHECK="$OUT_DIR/.$KIT_NAME.compiled.json"
trap 'rm -f "$COMPILED_CHECK"; cleanup_failed_outputs' EXIT
PYTHONPATH="$ROOT_DIR/adapter_service" "$PYTHON_BIN" \
  "$ROOT_DIR/adapter_service/tools/compile_format_rule_pack.py" \
  --template-docx "$ROOT_DIR/adapter_service/vendor/wx_doc_format_algorithm/assets/wx_template.docx" \
  --template-json "$ROOT_DIR/packaging/format-rule-sources/technical-document-template-rules.v1.0.0.json" \
  --structure-rules "$ROOT_DIR/packaging/format-rule-sources/technical-document-template-rules.v1.0.0.structure.json" \
  --output "$COMPILED_CHECK"
cmp "$COMPILED_CHECK" \
  "$ROOT_DIR/adapter_service/format_rule_packs/technical-document-template-rules.v1.0.0.json"
rm -f "$COMPILED_CHECK"

"$PYTHON_BIN" "$ROOT_DIR/packaging/check_python38_compatibility.py" \
  "$TMP_DIR/packages/adapter-start-kit/adapter_service" \
  "$TMP_DIR/scripts/check_python38_compatibility.py" \
  "$TMP_DIR/scripts/audit_delivery.py" \
  "$TMP_DIR/scripts/audit_v0252_delivery.py" \
  "$TMP_DIR/scripts/python38_delivery_runtime_gate.py" \
  "$TMP_DIR/scripts/python38_delivery_lifecycle_gate.py" \
  "$TMP_DIR/installer/release_transaction.py"

if ! command -v node >/dev/null 2>&1; then
  echo "plugin_contract_runtime_required=node"
  exit 1
fi
AI_WPS_HASH_CONTRACT_PYTHON="$PYTHON_BIN" node --test "$ROOT_DIR"/formal-plugin-kit/tests/*.test.js
echo "plugin_contract=passed"

find "$TMP_DIR" -type f -name '*.sh' -exec chmod 755 {} \;
find "$TMP_DIR/packages/adapter-start-kit/adapter_service" -type f -name '*.py' -exec chmod 755 {} \;

"$PYTHON_BIN" "$ROOT_DIR/packaging/audit_phase1_delivery.py" "$TMP_DIR" --write-hashes
"$PYTHON_BIN" "$ROOT_DIR/packaging/audit_v0252_delivery.py" "$TMP_DIR"
"$PYTHON_BIN" "$TMP_DIR/scripts/audit_v0252_delivery.py" "$TMP_DIR"

COPYFILE_DISABLE=1 tar -czf "$PENDING_ARCHIVE_PATH" -C "$OUT_DIR" "$KIT_NAME"
"$PYTHON38_BIN" "$ROOT_DIR/packaging/python38_delivery_lifecycle_gate.py" \
  "$PENDING_ARCHIVE_PATH" \
  --expected-version "$VERSION" \
  --baseline-archive "$BASELINE_ARCHIVE" \
  --baseline-version "$BASELINE_VERSION"

"$PYTHON_BIN" - "$PENDING_ARCHIVE_PATH" "$PENDING_CHECKSUM_PATH" "$(basename "$ARCHIVE_PATH")" <<'PY'
import hashlib
import sys
from pathlib import Path

archive_path = Path(sys.argv[1])
checksum_path = Path(sys.argv[2])
checksum_path.write_text(
    "{0}  {1}\n".format(hashlib.sha256(archive_path.read_bytes()).hexdigest(), sys.argv[3]),
    encoding="utf-8",
)
PY

"$PYTHON_BIN" "$ROOT_DIR/packaging/audit_v0252_delivery.py" "$TMP_DIR" \
  --archive "$PENDING_ARCHIVE_PATH" \
  --checksum-file "$PENDING_CHECKSUM_PATH" \
  --expected-archive-name "$(basename "$ARCHIVE_PATH")"

mv "$PENDING_ARCHIVE_PATH" "$ARCHIVE_PATH"
PUBLISHED_ARCHIVE="1"
mv "$PENDING_CHECKSUM_PATH" "$ARCHIVE_PATH.sha256"
PUBLISHED_ARCHIVE="0"
echo "v0252_delivery_candidate=$ARCHIVE_PATH status=candidate source_commit=$SOURCE_COMMIT"
trap - EXIT
