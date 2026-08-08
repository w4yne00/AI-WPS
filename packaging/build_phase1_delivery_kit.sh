#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
OUT_DIR="${1:-$ROOT_DIR/dist-phase1-delivery-kit}"
DATE_TAG="${DATE_TAG:-$(date '+%Y%m%d')}"
KIT_NAME="ai-wps-phase1-delivery-${DATE_TAG}-v0220"
TMP_DIR="$OUT_DIR/$KIT_NAME"

WORD_FORMAL_SRC="$ROOT_DIR/formal-plugin-kit/wps-ai-assistant_1.0.0"
EXCEL_FORMAL_SRC="$ROOT_DIR/formal-plugin-kit/wps-ai-assistant-et_1.0.0"
PPT_FORMAL_SRC="$ROOT_DIR/formal-plugin-kit/wps-ai-assistant-wpp_1.0.0"
ADAPTER_SRC="$ROOT_DIR/adapter-start-kit"
PIP_TAR="$ROOT_DIR/dist-offline-deps/kylin-v10-arm-py38-pip-bootstrap-20260506.tar.gz"
RUNTIME_TAR="$ROOT_DIR/dist-offline-deps/kylin-v10-arm-py38-runtime-deps-20260506.tar.gz"

rm -rf "$TMP_DIR"
mkdir -p "$TMP_DIR/packages/adapter-start-kit" "$TMP_DIR/docs" "$TMP_DIR/installer" "$TMP_DIR/scripts" "$TMP_DIR/wps-jsaddons"

cp -R "$ROOT_DIR/phase1-delivery-kit/." "$TMP_DIR/"
cp -R "$WORD_FORMAL_SRC" "$TMP_DIR/packages/wps-ai-assistant_1.0.0"
cp -R "$EXCEL_FORMAL_SRC" "$TMP_DIR/packages/wps-ai-assistant-et_1.0.0"
cp -R "$PPT_FORMAL_SRC" "$TMP_DIR/packages/wps-ai-assistant-wpp_1.0.0"
cp -R "$ADAPTER_SRC/." "$TMP_DIR/packages/adapter-start-kit/"
cp -R "$ROOT_DIR/adapter_service" "$TMP_DIR/packages/adapter-start-kit/"
cp -R "$ROOT_DIR/config" "$TMP_DIR/packages/adapter-start-kit/"
cp -R "$ROOT_DIR/templates" "$TMP_DIR/packages/adapter-start-kit/"
mkdir -p "$TMP_DIR/docs/operations" "$TMP_DIR/docs/prompt-templates" "$TMP_DIR/docs/import-templates"
cp "$ROOT_DIR/docs/operations/dify-smart-write-workflow.md" "$TMP_DIR/docs/operations/"
cp "$ROOT_DIR/docs/operations/dify-smart-imitation-workflow.md" "$TMP_DIR/docs/operations/"
cp "$ROOT_DIR/docs/operations/dify-document-review-workflow.md" "$TMP_DIR/docs/operations/"
cp "$ROOT_DIR/docs/operations/dify-format-review-workflow.md" "$TMP_DIR/docs/operations/"
cp "$ROOT_DIR/docs/operations/dify-excel-analysis-workflow.md" "$TMP_DIR/docs/operations/"
cp "$ROOT_DIR/docs/operations/dify-excel-formula-assistant-workflow.md" "$TMP_DIR/docs/operations/"
cp "$ROOT_DIR/docs/operations/dify-ppt-slide-assistant-workflow.md" "$TMP_DIR/docs/operations/"
cp "$ROOT_DIR/docs/operations/dify-ppt-structure-review-workflow.md" "$TMP_DIR/docs/operations/"
cp "$ROOT_DIR/docs/operations/workflow-profile-management.md" "$TMP_DIR/docs/operations/"
cp "$ROOT_DIR/docs/operations/writing-policy-library.md" "$TMP_DIR/docs/operations/"
cp "$ROOT_DIR/docs/writing-policy-sources.md" "$TMP_DIR/docs/"
cp "$ROOT_DIR/docs/prompt-templates/excel-smart-analysis-prompt-template.md" "$TMP_DIR/docs/prompt-templates/"
cp "$ROOT_DIR/docs/prompt-templates/excel-formula-assistant-prompt-template.md" "$TMP_DIR/docs/prompt-templates/"
cp "$ROOT_DIR/docs/prompt-templates/ppt-smart-summary-prompt-template.md" "$TMP_DIR/docs/prompt-templates/"
cp "$ROOT_DIR/docs/prompt-templates/ppt-structure-review-prompt-template.md" "$TMP_DIR/docs/prompt-templates/"

PYTHONPATH="$ROOT_DIR/adapter_service" "$PYTHON_BIN" - "$TMP_DIR/docs/import-templates" <<'PY'
from pathlib import Path
import sys

from app.services.writing_policy.imports import (
    generate_csv_template,
    generate_xlsx_template,
)

output_dir = Path(sys.argv[1])
(output_dir / "writing-policies-import-template.csv").write_bytes(
    generate_csv_template()
)
(output_dir / "writing-policies-import-template.xlsx").write_bytes(
    generate_xlsx_template()
)
PY

"$PYTHON_BIN" - "$TMP_DIR/release-manifest.json" "$DATE_TAG" <<'PY'
import json
from pathlib import Path
import sys

manifest_path = Path(sys.argv[1])
date_tag = sys.argv[2]
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
manifest["releaseDate"] = date_tag
manifest["versionRule"] = (
    "AI-WPS-P1-WORD-EXCEL-PPT-0.22.0-" + date_tag
)
manifest_path.write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
PY

tar -xzf "$PIP_TAR" -C "$TMP_DIR/packages"
mv "$TMP_DIR/packages/kylin-v10-arm-py38-pip-bootstrap-20260506" "$TMP_DIR/packages/kylin-v10-arm-py38-pip-bootstrap"

tar -xzf "$RUNTIME_TAR" -C "$TMP_DIR/packages"

rm -rf \
  "$TMP_DIR/packages/adapter-start-kit/run" \
  "$TMP_DIR/packages/adapter-start-kit/logs" \
  "$TMP_DIR/packages/adapter-start-kit/adapter_service/run" \
  "$TMP_DIR/packages/adapter-start-kit/adapter_service/logs" \
  "$TMP_DIR/packages/adapter-start-kit/config/adapter.json"
find "$TMP_DIR" -type d -name 'provider_api_keys' -prune -exec rm -rf {} +
find "$TMP_DIR" -type f \( \
  -name 'provider_api_key' \
  -o -name 'writing_policies.db' \
  -o -name 'writing_policies.db.backup-*' \
  -o -name '*.log' \
  -o -name '*.draft.csv' \
  -o -name '*.draft.xlsx' \
\) -delete
find "$TMP_DIR" \( -name '.DS_Store' -o -name '._*' -o -name '__pycache__' \) -exec rm -rf {} +
find "$TMP_DIR" -type f -name '*.sh' -exec chmod 755 {} \;
find "$TMP_DIR/packages/adapter-start-kit/adapter_service" -type f -name '*.py' -exec chmod 755 {} \;

"$PYTHON_BIN" - "$TMP_DIR" <<'PY'
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
manifest = json.loads((root / "release-manifest.json").read_text(encoding="utf-8"))
adapter_service_root = (
    root
    / "packages"
    / "adapter-start-kit"
    / "adapter_service"
)
sys.path.insert(0, str(adapter_service_root))
from app.services.writing_policy.packs import load_pack_snapshot

pack_root = adapter_service_root / "writing_policy_packs"
expected_packs = set(manifest["writingPolicyPacks"])
snapshot = load_pack_snapshot(pack_root)
actual_packs = {pack["packId"] for pack in snapshot.public_packs()}
if actual_packs != expected_packs:
    raise SystemExit(
        "writing policy pack inventory mismatch: expected=%s actual=%s"
        % (sorted(expected_packs), sorted(actual_packs))
    )
for required in (
    pack_root / "THIRD_PARTY_NOTICES.md",
    root / "docs" / "writing-policy-sources.md",
    root / manifest["excelFormulaAssistantAssets"]["operationsGuide"],
    root / manifest["excelFormulaAssistantAssets"]["promptTemplate"],
    root / manifest["pptStructureReviewAssets"]["operationsGuide"],
    root / manifest["pptStructureReviewAssets"]["promptTemplate"],
    root / "docs" / "import-templates" / "writing-policies-import-template.csv",
    root / "docs" / "import-templates" / "writing-policies-import-template.xlsx",
):
    if not required.is_file():
        raise SystemExit("missing delivery file: " + str(required.relative_to(root)))

for path in root.rglob("*"):
    relative = path.relative_to(root).as_posix()
    if path.is_dir() and path.name in {"logs", "provider_api_keys"}:
        raise SystemExit("runtime directory leaked into delivery: " + relative)
    if not path.is_file():
        continue
    if (
        path.name in {"adapter.json", "provider_api_key", "writing_policies.db"}
        or path.name.startswith("writing_policies.db.backup-")
        or path.suffix == ".log"
        or ".draft." in path.name
    ):
        raise SystemExit("runtime or draft file leaked into delivery: " + relative)
    if path.suffix in {".csv", ".xlsx"} and "docs/import-templates/" not in relative:
        raise SystemExit("non-template import content leaked into delivery: " + relative)
PY

ARCHIVE_PATH="$OUT_DIR/$KIT_NAME.tar.gz"
COPYFILE_DISABLE=1 tar -czf "$ARCHIVE_PATH" -C "$OUT_DIR" "$KIT_NAME"

"$PYTHON_BIN" - "$ARCHIVE_PATH" <<'PY'
import hashlib
from pathlib import Path
import sys

archive_path = Path(sys.argv[1])
digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
checksum_path = archive_path.with_name(archive_path.name + ".sha256")
checksum_path.write_text(
    "{0}  {1}\n".format(digest, archive_path.name),
    encoding="utf-8",
)
PY

echo "Phase1 delivery kit created at $ARCHIVE_PATH"
echo "Phase1 delivery checksum created at $ARCHIVE_PATH.sha256"
