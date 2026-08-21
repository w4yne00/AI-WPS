#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
OUT_DIR="${1:-$ROOT_DIR/dist-phase1-delivery-kit}"
DATE_TAG="${DATE_TAG:-$(date '+%Y%m%d')}"
KIT_NAME="ai-wps-format-rule-assets-${DATE_TAG}-v0250"
TMP_DIR="$OUT_DIR/$KIT_NAME"
ARCHIVE_PATH="$OUT_DIR/$KIT_NAME.tar.gz"
SOURCE_ALLOWLIST="$ROOT_DIR/packaging/delivery-sources-v0250-format-rules.json"
COMPILED_CHECK="$OUT_DIR/.$KIT_NAME.compiled.json"

if [[ ! "$DATE_TAG" =~ ^[0-9]{8}$ ]]; then
  echo "format_rule_assets_date_invalid=$DATE_TAG"
  exit 1
fi
if [ -e "$ARCHIVE_PATH" ] || [ -e "$TMP_DIR" ] || [ -e "$COMPILED_CHECK" ]; then
  echo "format_rule_assets_output_exists=$ARCHIVE_PATH"
  exit 1
fi
cleanup() {
  rm -rf "$TMP_DIR" "$COMPILED_CHECK"
}
trap cleanup EXIT
mkdir -p "$OUT_DIR"

PYTHONPATH="$ROOT_DIR/adapter_service" "$PYTHON_BIN" \
  "$ROOT_DIR/adapter_service/tools/compile_format_rule_pack.py" \
  --template-docx "$ROOT_DIR/adapter_service/vendor/wx_doc_format_algorithm/assets/wx_template.docx" \
  --template-json "$ROOT_DIR/templates/company/technical-file-format-requirements.json" \
  --structure-rules "$ROOT_DIR/templates/company/technical-file-structure-rules.json" \
  --output "$COMPILED_CHECK"
cmp "$COMPILED_CHECK" \
  "$ROOT_DIR/adapter_service/format_rule_packs/technical-document-template-rules.v1.0.0.json"

"$PYTHON_BIN" "$ROOT_DIR/packaging/assemble_phase1_delivery.py" \
  --repo-root "$ROOT_DIR" \
  --source-allowlist "$SOURCE_ALLOWLIST" \
  --output "$TMP_DIR"

"$PYTHON_BIN" "$ROOT_DIR/packaging/check_python38_compatibility.py" \
  "$ROOT_DIR/adapter_service/app/services/word/authorized_format_algorithm.py" \
  "$ROOT_DIR/adapter_service/app/services/word/format_rule_pack.py" \
  "$ROOT_DIR/adapter_service/app/services/word/format_reviewer.py" \
  "$ROOT_DIR/adapter_service/app/services/word/format_issue_support.py" \
  "$ROOT_DIR/adapter_service/app/core/models.py" \
  "$ROOT_DIR/adapter_service/tools/compile_format_rule_pack.py" \
  "$ROOT_DIR/adapter_service/vendor/wx_doc_format_algorithm/algorithm.py" \
  "$ROOT_DIR/packaging/audit_format_rule_assets.py"

"$PYTHON_BIN" "$ROOT_DIR/packaging/audit_format_rule_assets.py" "$TMP_DIR"
COPYFILE_DISABLE=1 tar -czf "$ARCHIVE_PATH" -C "$OUT_DIR" "$KIT_NAME"
echo "format_rule_assets_archive=$ARCHIVE_PATH status=candidate"
