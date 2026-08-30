#!/usr/bin/env python3
"""Finalize the neutral v0.26.0-preview.1 delivery tree."""

import argparse
from datetime import datetime
import hashlib
import json
import re
import tarfile
from pathlib import Path
from typing import List, Optional, Set


VERSION = "0.26.0-preview.1"
BASELINE_VERSION = "0.25.3-alpha"
SOURCE_COMMIT_RE = re.compile(r"^[0-9a-f]{7,40}$")
TEXT_SUFFIXES = {
    ".css",
    ".html",
    ".js",
    ".json",
    ".md",
    ".py",
    ".sh",
    ".txt",
    ".xml",
    ".yml",
}
ARCHIVE_PREFIX = "ai-wps-delivery-"
VERSION_REWRITE_EXCLUDED_PATHS = {
    "README.md",
    "docs/v0260-preview1-delivery.md",
    "docs/v0260-preview1-target-machine-acceptance.md",
    "docs/v0260-preview1-candidate-status.json",
    "scripts/audit_delivery.py",
    "scripts/audit_v0260_preview1_delivery.py",
    "scripts/python38_delivery_lifecycle_gate.py",
    "scripts/python38_delivery_runtime_gate.py",
}

LEGACY_OUTPUT_PATHS = {
    "installer/install_phase1.sh",
    "scripts/phase1_smoke_test.sh",
    "docs/phase1-acceptance-checklist.md",
    "docs/phase1-acceptance-record.md",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def candidate_archive_name(date_tag: str, source_commit: str) -> str:
    return "{0}{1}-{2}-v0260-preview1.tar.gz".format(
        ARCHIVE_PREFIX, date_tag, source_commit[:7]
    )


def _manifest_from_archive(archive: Path) -> dict:
    try:
        with tarfile.open(str(archive), "r:gz") as handle:
            member = next(
                item
                for item in handle.getmembers()
                if Path(item.name).name == "release-manifest.json" and item.isfile()
            )
            extracted = handle.extractfile(member)
            if extracted is None:
                raise ValueError("V0260_BASELINE_MANIFEST_UNREADABLE")
            manifest = json.loads(extracted.read().decode("utf-8"))
    except (OSError, tarfile.TarError, StopIteration, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("V0260_BASELINE_ARCHIVE_INVALID") from exc
    if not isinstance(manifest, dict):
        raise ValueError("V0260_BASELINE_MANIFEST_INVALID")
    return manifest


def baseline_metadata(archive: Path, expected_version: str) -> dict:
    if not archive.is_file():
        raise ValueError("V0260_BASELINE_ARCHIVE_MISSING")
    manifest = _manifest_from_archive(archive)
    if manifest.get("version") != expected_version:
        raise ValueError("V0260_BASELINE_VERSION_INVALID")
    if manifest.get("deliveryPolicy", {}).get("status") != "candidate":
        raise ValueError("V0260_BASELINE_NOT_CANDIDATE")
    return {
        "requiredProductVersion": expected_version,
        "archiveName": archive.name,
        "archiveSha256": sha256(archive),
        "sourceStatus": "candidate",
    }


def _non_empty_lines(content: str) -> List[str]:
    return [line for line in content.splitlines() if line and not line.isspace()]


def _legacy_path(relative: str) -> bool:
    if relative in LEGACY_OUTPUT_PATHS:
        return True
    if relative.startswith("docs/v025"):
        return True
    if relative.startswith("scripts/audit_v025"):
        return True
    return False


def remove_legacy_delivery_files(root: Path) -> Set[str]:
    removed: Set[str] = set()
    for path in sorted(root.rglob("*"), reverse=True):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if _legacy_path(relative):
            path.unlink()
            removed.add(relative)

    allowlist_path = root / "release-allowlist.json"
    if allowlist_path.is_file():
        allowlist = json.loads(allowlist_path.read_text(encoding="utf-8"))
        for key in ("files", "generatedFiles"):
            allowlist[key] = [
                item
                for item in allowlist.get(key, [])
                if str(item) not in removed and not _legacy_path(str(item))
            ]
        allowlist_path.write_text(
            json.dumps(allowlist, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return removed


def rewrite_versions(root: Path) -> None:
    old_versions = (
        "0.23.1-alpha",
        "0.24.0-alpha",
        "0.25.0-alpha",
        "0.25.1-alpha",
        "0.25.2-alpha",
        "0.25.3-alpha",
    )
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if path.relative_to(root).as_posix() in VERSION_REWRITE_EXCLUDED_PATHS:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        updated = content
        for old_version in old_versions:
            updated = updated.replace(old_version, VERSION)
        if path.relative_to(root).as_posix() == "packages/adapter-start-kit/README.md":
            updated = updated.replace("ai-wps-phase1", "ai-wps")
            updated = updated.replace("Phase 1", "Preview")
        if updated != content:
            path.write_text(updated, encoding="utf-8")


def rewrite_current_delivery_references(root: Path) -> None:
    replacements = (
        ("installer/install_phase1.sh", "installer/install_ai_wps.sh"),
        ("scripts/phase1_smoke_test.sh", "scripts/ai_wps_smoke_test.sh"),
        ("phase1_install_start=true", "ai_wps_install_start=true"),
        ("phase1_install_done=true", "ai_wps_install_done=true"),
        ("phase1_smoke_start=true", "ai_wps_smoke_start=true"),
        ("phase1_smoke_done=true", "ai_wps_smoke_done=true"),
        (
            "docs/phase1-acceptance-record.md",
            "docs/v0260-preview1-target-machine-acceptance.md",
        ),
        ("$HOME/ai-wps-phase1", "$HOME/ai-wps"),
        ("Phase 1 WPS AI assistant", "AI-WPS Preview assistant"),
        (
            "Formal Phase 1 WPS AI assistant plugin.",
            "Formal AI-WPS Preview assistant plugin.",
        ),
        (
            "# Phase 1 adapter service package.",
            "# AI-WPS Preview adapter service package.",
        ),
    )
    audit_script = "scripts/audit_v0260_preview1_delivery.py"
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if path.relative_to(root).as_posix() == audit_script:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        updated = content
        for old, new in replacements:
            updated = updated.replace(old, new)
        if updated != content:
            path.write_text(updated, encoding="utf-8")


def _replace_function(content: str, function_name: str, replacement: str) -> str:
    marker = function_name + "() {"
    start = content.find(marker)
    if start < 0:
        raise ValueError("V0260_INSTALLER_FUNCTION_MISSING {0}".format(function_name))
    brace = content.find("{", start)
    depth = 0
    end = None
    for index in range(brace, len(content)):
        character = content[index]
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                end = index + 1
                break
    if end is None:
        raise ValueError("V0260_INSTALLER_FUNCTION_UNTERMINATED {0}".format(function_name))
    return content[:start] + replacement.rstrip() + content[end:]


def neutralize_installer(root: Path) -> None:
    path = root / "installer/install_ai_wps.sh"
    if not path.is_file():
        raise ValueError("V0260_INSTALLER_MISSING")
    content = path.read_text(encoding="utf-8")
    replacements = (
        ('bash "$DELIVERY_ROOT/installer/install_phase1.sh"', 'bash "$DELIVERY_ROOT/installer/install_ai_wps.sh"'),
        ("recovery_command=bash installer/install_phase1.sh", "recovery_command=bash installer/install_ai_wps.sh"),
        ('phase1_install_start=true', 'ai_wps_install_start=true'),
        ('phase1_install_done=true', 'ai_wps_install_done=true'),
        ('scripts/phase1_smoke_test.sh', 'scripts/ai_wps_smoke_test.sh'),
        ('INSTALL_ROOT="${AI_WPS_INSTALL_ROOT:-$TARGET_HOME/ai-wps-phase1}"', 'INSTALL_ROOT="${AI_WPS_INSTALL_ROOT:-$TARGET_HOME/ai-wps}"'),
        ('RELEASE_VERSION="0.23.1-alpha"', 'RELEASE_VERSION="{0}"'.format(VERSION)),
    )
    for old, new in replacements:
        content = content.replace(old, new)

    home_path_line = '  local home_path=""\n'
    if home_path_line not in content:
        raise ValueError("V0260_TARGET_HOME_RESOLUTION_MISSING")
    content = content.replace(
        home_path_line,
        home_path_line
        + '  if [ -n "$TARGET_HOME_ARG" ]; then\n'
        + '    case "$TARGET_HOME_ARG" in\n'
        + '      /*) printf \'%s\\n\' "$TARGET_HOME_ARG"; return 0 ;;\n'
        + '      *) fail "target_home_must_be_absolute" ;;\n'
        + '    esac\n'
        + '  fi\n',
        1,
    )

    install_root_line = '  INSTALL_ROOT="${AI_WPS_INSTALL_ROOT:-$TARGET_HOME/ai-wps}"\n'
    if install_root_line not in content:
        raise ValueError("V0260_INSTALL_ROOT_ASSIGNMENT_MISSING")
    content = content.replace(
        install_root_line,
        install_root_line
        + '  LEGACY_PHASE1_INSTALL_ROOT="$TARGET_HOME/ai-wps-phase1"\n',
        1,
    )

    legacy_function = '''
preview_canonical_path() {
  local path="$1" probe base canonical_root candidate component
  local -a suffix=()
  path="${path%/}"
  [ -n "$path" ] || path="/"
  case "$path" in
    /*) ;;
    *) fail "preview_path_must_be_absolute value=$path" ;;
  esac

  probe="$path"
  while [ ! -e "$probe" ] && [ ! -L "$probe" ]; do
    [ "$probe" != "/" ] || break
    base="${probe##*/}"
    if [ "${#suffix[@]}" -eq 0 ]; then
      suffix=("$base")
    else
      suffix=("$base" "${suffix[@]}")
    fi
    probe="${probe%/*}"
    [ -n "$probe" ] || probe="/"
  done
  [ -d "$probe" ] || fail "preview_path_canonicalize_failed value=$path"
  canonical_root="$(cd -P "$probe" && pwd -P)" \
    || fail "preview_path_canonicalize_failed value=$path"

  for component in "${suffix[@]-}"; do
    case "$component" in
      ''|.) ;;
      ..)
        [ "$canonical_root" != "/" ] || continue
        canonical_root="${canonical_root%/*}"
        [ -n "$canonical_root" ] || canonical_root="/"
        ;;
      *)
        if [ "$canonical_root" = "/" ]; then
          candidate="/$component"
        else
          candidate="$canonical_root/$component"
        fi
        if [ -e "$candidate" ] || [ -L "$candidate" ]; then
          [ -d "$candidate" ] || fail "preview_path_canonicalize_failed value=$path"
          canonical_root="$(cd -P "$candidate" && pwd -P)" \
            || fail "preview_path_canonicalize_failed value=$path"
        else
          canonical_root="$candidate"
        fi
        ;;
    esac
  done
  printf '%s\\n' "$canonical_root"
}

preview_paths_overlap() {
  local left="${1%/}" right="${2%/}"
  [ -n "$left" ] || left="/"
  [ -n "$right" ] || right="/"
  case "$left/" in
    "$right/"*) return 0 ;;
  esac
  case "$right/" in
    "$left/"*) return 0 ;;
  esac
  return 1
}

preview_reject_legacy_path() {
  local label="$1" path="$2" canonical_path canonical_legacy
  canonical_path="$(preview_canonical_path "$path")"
  canonical_legacy="$(preview_canonical_path "$LEGACY_PHASE1_INSTALL_ROOT")"
  if preview_paths_overlap "$canonical_path" "$canonical_legacy"; then
    fail "preview_path_conflicts_with_legacy name=$label path=$path"
  fi
}

detect_legacy_phase1_install() {
  preview_reject_legacy_path "install_root" "$INSTALL_ROOT"
  preview_reject_legacy_path "state_dir" "${AI_WPS_STATE_DIR:-$INSTALL_ROOT/state}"
  preview_reject_legacy_path "backup_dir" "${AI_WPS_BACKUP_DIR:-$INSTALL_ROOT/backups}"
  preview_reject_legacy_path "var_dir" "${AI_WPS_VAR_DIR:-$INSTALL_ROOT/var}"
  if [ -e "$LEGACY_PHASE1_INSTALL_ROOT" ] || [ -L "$LEGACY_PHASE1_INSTALL_ROOT" ]; then
    log "legacy_phase1_install_detected=true path=$LEGACY_PHASE1_INSTALL_ROOT"
    log "legacy_phase1_action=read_only"
    log "manual_reinstall_required=true"
    log "manual_reconfigure_required=true"
    log "legacy_runtime_data_migrated=false"
    log "legacy_install_deleted=false"
  else
    log "legacy_phase1_install_detected=false"
  fi
}
'''
    insertion_point = content.index("\nfail() {")
    content = content[:insertion_point] + legacy_function + content[insertion_point:]

    content = _replace_function(
        content,
        "legacy_runtime_state_exists",
        "",
    )
    prepare_start = content.index("prepare_runtime_state() {")
    migration_start = content.find("  if legacy_runtime_state_exists; then", prepare_start)
    fresh_state_start = content.find('  mkdir -p "$CANDIDATE_STATE"', migration_start)
    if migration_start < 0 or fresh_state_start < 0:
        raise ValueError("V0260_LEGACY_MIGRATION_BLOCK_MISSING")
    content = (
        content[:migration_start]
        + "  # Preview baseline deliberately starts a new state and never migrates legacy data.\n"
        + content[fresh_state_start:]
    )

    call_marker = "resolve_installation_principal\nresolve_python_binary"
    if call_marker not in content:
        raise ValueError("V0260_INSTALLER_SETUP_SEQUENCE_MISSING")
    content = content.replace(
        call_marker,
        "resolve_installation_principal\ndetect_legacy_phase1_install\nresolve_python_binary",
        1,
    )
    state_assignment = 'VAR_DIR="${AI_WPS_VAR_DIR:-$INSTALL_ROOT/var}"\n'
    if state_assignment not in content:
        raise ValueError("V0260_RUNTIME_PATH_ASSIGNMENT_MISSING")
    existing_install_guard = '''
preview_install_layout_exists() {
  local relative
  for relative in current releases state backups var config run adapter-start-kit; do
    if [ -e "$INSTALL_ROOT/$relative" ] || [ -L "$INSTALL_ROOT/$relative" ]; then
      return 0
    fi
  done
  for configured_path in "$STATE_DIR" "$BACKUP_DIR" "$VAR_DIR"; do
    if [ -e "$configured_path" ] || [ -L "$configured_path" ]; then
      return 0
    fi
  done
  return 1
}

validate_existing_preview_install() {
  local manifest
  preview_install_layout_exists || return 0
  manifest="$INSTALL_ROOT/current/release-manifest.json"
  [ -f "$manifest" ] || fail "preview_existing_install_manifest_required"
  if ! "$PYTHON_BIN" - "$manifest" "$RELEASE_VERSION" <<'PY' >/dev/null 2>&1
import json
from pathlib import Path
import sys

manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
expected = sys.argv[2]
assert manifest.get("schemaVersion") == 1
assert manifest.get("product") == "AI-WPS"
assert manifest.get("productChannel") == "preview"
assert manifest.get("version") == expected
adapter = manifest.get("adapter", {})
assert adapter.get("version") == expected
assert adapter.get("systemPromptManifest") == (
    "packages/adapter-start-kit/adapter_service/system_prompts/manifest.json"
)
assert adapter.get("systemPromptCount") == 8
delivery = manifest.get("deliveryPolicy", {})
assert delivery.get("status") == "candidate"
assert delivery.get("sourceAssembly") == "explicit-allowlist"
assert delivery.get("allowlist") == "release-allowlist.json"
assert delivery.get("fileHashes") == "release-file-hashes.json"
generation = manifest.get("releaseGenerationPolicy", {})
assert generation.get("switchStrategy") == "durable-compensating-rename"
assert generation.get("currentPointer") == "current"
assert generation.get("components") == [
    "adapter_release",
    "word_plugin",
    "excel_plugin",
    "ppt_plugin",
    "publish_manifest",
    "runtime_state_snapshot",
    "current_pointer",
]
assert manifest.get("installationPolicy") == {
    "installer": "installer/install_ai_wps.sh",
    "defaultInstallRoot": "$TARGET_HOME/ai-wps",
    "legacyInstallRoot": "$TARGET_HOME/ai-wps-phase1",
    "legacyHandling": "read-only-detect-manual-reinstall-reconfigure",
    "migratesLegacyRuntimeData": False,
    "deletesLegacyInstall": False,
}
PY
  then
    fail "preview_existing_install_manifest_invalid"
  fi
}
'''
    content = content.replace(
        state_assignment,
        state_assignment + existing_install_guard,
        1,
    )
    validate_marker = 'validate_target_path "var_dir" "$VAR_DIR"\n'
    if validate_marker not in content:
        raise ValueError("V0260_RUNTIME_PATH_VALIDATION_MISSING")
    content = content.replace(
        validate_marker,
        validate_marker + "validate_existing_preview_install\n",
        1,
    )
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def update_prompt_manifest(root: Path) -> None:
    path = root / "packages/adapter-start-kit/adapter_service/system_prompts/manifest.json"
    if not path.is_file():
        raise ValueError("V0260_PROMPT_MANIFEST_MISSING")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["release"] = VERSION
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def update_format_asset_manifest(root: Path) -> None:
    path = root / "format-rule-assets-manifest.json"
    if not path.is_file():
        return
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if "deliveryVersion" in manifest:
        manifest["deliveryVersion"] = VERSION
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_candidate_records(
    root: Path,
    date_tag: str,
    source_commit: str,
    candidate_build_id: str,
    archive_name: str,
    acceptance_issue: int,
) -> None:
    status_path = root / "docs/v0260-preview1-candidate-status.json"
    if not status_path.is_file():
        raise ValueError("V0260_CANDIDATE_STATUS_MISSING")
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status["records"] = [
        {
            "candidateBuildId": candidate_build_id,
            "archiveName": archive_name,
            "archiveChecksumFile": archive_name + ".sha256",
            "sourceCommit": source_commit,
            "status": "candidate",
            "recordedAt": date_tag,
        }
    ]
    status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    acceptance_path = root / "docs/v0260-preview1-target-machine-acceptance.md"
    content = acceptance_path.read_text(encoding="utf-8")
    replacements = {
        "- 候选标识：待构建时由 `prepare_v0260_preview1_delivery.py` 写入":
            "- 候选标识：`{0}-{1}`".format(date_tag, source_commit[:7]),
        "- 归档文件：待构建时由构建脚本写入":
            "- 归档文件：`{0}`".format(archive_name),
        "- 归档 SHA-256：待构建时由构建脚本写入":
            "- 归档 SHA-256：构建归档后写入包外校验文件",
    }
    for old, new in replacements.items():
        content = content.replace(old, new)
    content = content.replace(
        "首次 Preview 验收前保持 `manual-pending`",
        "首次 Preview 验收前保持 `manual-pending`（Issue #{0}）".format(acceptance_issue),
    )
    acceptance_path.write_text(content, encoding="utf-8")


def update_manifest(
    root: Path,
    date_tag: str,
    source_commit: str,
    baseline: dict,
    archive_name: str,
    acceptance_issue: int,
) -> str:
    path = root / "release-manifest.json"
    if not path.is_file():
        raise ValueError("V0260_RELEASE_MANIFEST_MISSING")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    candidate_build_id = (
        "AI-WPS-WORD-EXCEL-PPT-{0}-{1}-{2}".format(
            VERSION, date_tag, source_commit[:7]
        )
    )
    manifest["product"] = "AI-WPS"
    manifest["productChannel"] = "preview"
    manifest["version"] = VERSION
    manifest["releaseDate"] = date_tag
    manifest["versionRule"] = candidate_build_id
    manifest["adapter"]["version"] = VERSION
    manifest["deliveryPolicy"] = {
        "status": "candidate",
        "sourceAssembly": "explicit-allowlist",
        "allowlist": "release-allowlist.json",
        "fileHashes": "release-file-hashes.json",
        "auditScript": "scripts/audit_delivery.py",
        "candidateAuditScript": "scripts/audit_v0260_preview1_delivery.py",
        "lifecycleGate": "scripts/python38_delivery_lifecycle_gate.py",
        "targetAcceptanceRequired": True,
        "automatedGates": [
            "allowlist",
            "python38-compatibility",
            "plugin-contract",
            "format-rule-compile",
            "preview-identity-audit",
            "python38-lifecycle",
        ],
    }
    manifest["baseline"] = baseline
    manifest["targetAcceptanceIssue"] = acceptance_issue
    manifest["targetAcceptance"] = {
        "status": "manual-pending",
        "required": True,
        "doesNotCloseIssue": True,
    }
    manifest["candidateEvidence"] = {
        "candidateBuildId": candidate_build_id,
        "sourceCommit": source_commit,
        "archiveName": archive_name,
        "archiveChecksumFile": archive_name + ".sha256",
        "automatedResult": "candidate",
        "acceptanceRecord": "Issue #{0}".format(acceptance_issue),
    }
    manifest["installationPolicy"] = {
        "installer": "installer/install_ai_wps.sh",
        "defaultInstallRoot": "$TARGET_HOME/ai-wps",
        "legacyInstallRoot": "$TARGET_HOME/ai-wps-phase1",
        "legacyHandling": "read-only-detect-manual-reinstall-reconfigure",
        "migratesLegacyRuntimeData": False,
        "deletesLegacyInstall": False,
    }
    manifest["upgradePolicy"] = {
        "baselineVersion": VERSION,
        "futureCompatibleUpgradesPreserve": [
            "config",
            "api_keys",
            "runtime_data",
            "backups",
        ],
        "rebuildIdentity": "candidate-build-id-and-archive-sha256",
    }
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return candidate_build_id


def prepare(
    root: Path,
    date_tag: str,
    baseline_archive: Path,
    baseline_version: str,
    source_commit: str,
    acceptance_issue: int,
) -> None:
    if not root.is_dir():
        raise ValueError("V0260_DELIVERY_ROOT_MISSING")
    if not re.fullmatch(r"[0-9]{8}", date_tag):
        raise ValueError("V0260_DATE_INVALID")
    try:
        datetime.strptime(date_tag, "%Y%m%d")
    except ValueError as exc:
        raise ValueError("V0260_DATE_INVALID") from exc
    if baseline_version != BASELINE_VERSION:
        raise ValueError("V0260_BASELINE_VERSION_REQUIRED")
    if not SOURCE_COMMIT_RE.fullmatch(source_commit):
        raise ValueError("V0260_SOURCE_COMMIT_INVALID")

    baseline = baseline_metadata(baseline_archive, baseline_version)
    archive_name = candidate_archive_name(date_tag, source_commit)
    rewrite_versions(root)
    rewrite_current_delivery_references(root)
    remove_legacy_delivery_files(root)
    neutralize_installer(root)
    update_prompt_manifest(root)
    update_format_asset_manifest(root)
    candidate_build_id = update_manifest(
        root,
        date_tag,
        source_commit,
        baseline,
        archive_name,
        acceptance_issue,
    )
    allowlist_path = root / "release-allowlist.json"
    allowlist = json.loads(allowlist_path.read_text(encoding="utf-8"))
    allowlist["version"] = VERSION
    allowlist_path.write_text(json.dumps(allowlist, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_candidate_records(
        root,
        date_tag,
        source_commit,
        candidate_build_id,
        archive_name,
        acceptance_issue,
    )
    print("v0260_preview1_delivery_prepared=passed version={0}".format(VERSION))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--date", required=True)
    parser.add_argument("--baseline-archive", required=True, type=Path)
    parser.add_argument("--baseline-version", default=BASELINE_VERSION)
    parser.add_argument("--acceptance-issue", default=119, type=int)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args(argv)
    try:
        prepare(
            args.root.resolve(),
            args.date,
            args.baseline_archive.resolve(),
            args.baseline_version,
            args.source_commit,
            args.acceptance_issue,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print("v0260_preview1_delivery_prepared=failed {0}".format(exc))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
