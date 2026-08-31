#!/usr/bin/env python3
"""Audit the neutral v0.26.0-preview.1 delivery boundary."""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set


VERSION = "0.26.0-preview.1"
VERSION_RULE_RE = re.compile(
    r"^AI-WPS-WORD-EXCEL-PPT-0\.26\.0-preview\.1-"
    r"(?P<date>[0-9]{8})-(?P<source>[0-9a-f]{7,40})$"
)
BASELINE_ARCHIVE_RE = re.compile(
    r"^ai-wps-phase1-delivery-[0-9]{8}(?:-[0-9a-f]{7,40})?-v0253\.tar\.gz$"
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
FORBIDDEN_OUTPUT_PATHS = {
    "installer/install_phase1.sh",
    "scripts/phase1_smoke_test.sh",
}
REQUIRED_OUTPUTS = {
    "README.md",
    "release-manifest.json",
    "release-allowlist.json",
    "installer/install_ai_wps.sh",
    "scripts/ai_wps_smoke_test.sh",
    "scripts/audit_delivery.py",
    "scripts/audit_v0260_preview1_delivery.py",
    "scripts/python38_delivery_runtime_gate.py",
    "scripts/python38_delivery_lifecycle_gate.py",
    "docs/v0260-preview1-target-machine-acceptance.md",
    "docs/v0260-preview1-candidate-status.json",
    "release-file-hashes.json",
}


class DeliveryFailure(RuntimeError):
    pass


def load_json(path: Path, code: str) -> Dict:
    if not path.is_file():
        raise DeliveryFailure(code)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DeliveryFailure(code) from exc
    if not isinstance(value, dict):
        raise DeliveryFailure(code)
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def delivery_files(root: Path) -> Set[str]:
    files: Set[str] = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise DeliveryFailure(
                "V0260_DELIVERY_SYMLINK_REJECTED {0}".format(
                    path.relative_to(root).as_posix()
                )
            )
        if path.is_file():
            files.add(path.relative_to(root).as_posix())
    return files


def audit_inventory(root: Path, actual: Set[str], allowlist: Dict) -> None:
    if allowlist.get("schemaVersion") != 1:
        raise DeliveryFailure("V0260_ALLOWLIST_SCHEMA_INVALID")
    if allowlist.get("version") != VERSION:
        raise DeliveryFailure("V0260_ALLOWLIST_VERSION_INVALID")
    allowed = set(str(item) for item in allowlist.get("files", []))
    generated = set(str(item) for item in allowlist.get("generatedFiles", []))
    if actual - allowed - generated:
        raise DeliveryFailure(
            "V0260_FILE_NOT_ALLOWLISTED {0}".format(sorted(actual - allowed - generated)[0])
        )
    if allowed - actual:
        raise DeliveryFailure(
            "V0260_ALLOWLISTED_FILE_MISSING {0}".format(sorted(allowed - actual)[0])
        )
    missing_required = sorted(REQUIRED_OUTPUTS - actual)
    if missing_required:
        raise DeliveryFailure("V0260_REQUIRED_OUTPUT_MISSING {0}".format(missing_required[0]))
    forbidden = sorted(
        relative
        for relative in actual
        if relative in FORBIDDEN_OUTPUT_PATHS
        or "/phase1" in "/" + relative.lower()
        or relative.lower().startswith("docs/v025")
        or relative.lower().startswith("scripts/audit_v025")
    )
    if forbidden:
        raise DeliveryFailure("V0260_LEGACY_OUTPUT_PATH {0}".format(forbidden[0]))


def audit_manifest(root: Path, manifest: Dict) -> None:
    if manifest.get("schemaVersion") != 1:
        raise DeliveryFailure("V0260_MANIFEST_SCHEMA_INVALID")
    if manifest.get("product") != "AI-WPS":
        raise DeliveryFailure("V0260_PRODUCT_IDENTITY_INVALID")
    if manifest.get("productChannel") != "preview":
        raise DeliveryFailure("V0260_PRODUCT_CHANNEL_INVALID")
    if manifest.get("version") != VERSION:
        raise DeliveryFailure("V0260_VERSION_INVALID")
    version_rule = str(manifest.get("versionRule", ""))
    version_rule_match = VERSION_RULE_RE.fullmatch(version_rule)
    if version_rule_match is None:
        raise DeliveryFailure("V0260_VERSION_RULE_INVALID")
    if "phase1" in version_rule.lower() or "p1-" in version_rule.lower():
        raise DeliveryFailure("V0260_VERSION_RULE_LEGACY_IDENTITY")
    if manifest.get("releaseDate") != version_rule_match.group("date"):
        raise DeliveryFailure("V0260_RELEASE_DATE_INVALID")

    adapter = manifest.get("adapter", {})
    if adapter.get("version") != VERSION or adapter.get("systemPromptCount") != 9:
        raise DeliveryFailure("V0260_ADAPTER_IDENTITY_INVALID")
    if adapter.get("systemPromptManifest") != (
        "packages/adapter-start-kit/adapter_service/system_prompts/manifest.json"
    ):
        raise DeliveryFailure("V0260_PROMPT_MANIFEST_PATH_INVALID")
    format_review = manifest.get("formatReview", {})
    reference_workflows = format_review.get("referenceWorkflows")
    if (
        format_review.get("enabledByDefault") is not True
        or format_review.get("featureSwitch")
        != "AI_WPS_ENABLE_DETERMINISTIC_FORMAT_REVIEW"
        or format_review.get("rulePackManifest") != "format-rule-assets-manifest.json"
        or not isinstance(reference_workflows, list)
        or set(reference_workflows)
        != {
            "reference-workflows/format-semantics-text-v1.yml",
            "reference-workflows/format-semantics-vision-v1.yml",
        }
    ):
        raise DeliveryFailure("V0260_FORMAT_REVIEW_POLICY_INVALID")
    visual_policy = manifest.get("visualPolicy", {})
    if (
        visual_policy.get("enabledByDefault") is not True
        or visual_policy.get("runtimeMasterSwitch")
        != "formatReview.imageSemantics.enabled"
        or visual_policy.get("requiresWpsAcceptance") is not False
        or visual_policy.get("pixelExportWhenDisabled") is not False
        or visual_policy.get("pixelUploadWhenDisabled") is not False
        or visual_policy.get("imageSlotAllocationWhenDisabled") is not False
    ):
        raise DeliveryFailure("V0260_VISUAL_POLICY_INVALID")

    policy = manifest.get("deliveryPolicy", {})
    required_policy = {
        "status": "candidate",
        "sourceAssembly": "explicit-allowlist",
        "allowlist": "release-allowlist.json",
        "fileHashes": "release-file-hashes.json",
        "auditScript": "scripts/audit_delivery.py",
        "candidateAuditScript": "scripts/audit_v0260_preview1_delivery.py",
        "lifecycleGate": "scripts/python38_delivery_lifecycle_gate.py",
        "targetAcceptanceRequired": True,
    }
    if any(policy.get(key) != value for key, value in required_policy.items()):
        raise DeliveryFailure("V0260_DELIVERY_POLICY_INVALID")

    installation = manifest.get("installationPolicy", {})
    expected_installation = {
        "installer": "installer/install_ai_wps.sh",
        "defaultInstallRoot": "$TARGET_HOME/ai-wps",
        "legacyInstallRoot": "$TARGET_HOME/ai-wps-phase1",
        "legacyHandling": "read-only-detect-manual-reinstall-reconfigure",
        "migratesLegacyRuntimeData": False,
        "deletesLegacyInstall": False,
    }
    if installation != expected_installation:
        raise DeliveryFailure("V0260_INSTALLATION_POLICY_INVALID")

    target_acceptance = manifest.get("targetAcceptance", {})
    if (
        manifest.get("targetAcceptanceIssue") != 120
        or target_acceptance.get("status") != "manual-pending"
        or target_acceptance.get("required") is not True
        or target_acceptance.get("doesNotCloseIssue") is not True
    ):
        raise DeliveryFailure("V0260_TARGET_ACCEPTANCE_POLICY_INVALID")

    evidence = manifest.get("candidateEvidence", {})
    if evidence.get("automatedResult") != "candidate":
        raise DeliveryFailure("V0260_CANDIDATE_STATUS_INVALID")
    expected_archive_name = (
        "ai-wps-delivery-{0}-{1}-v0260-preview1.tar.gz".format(
            version_rule_match.group("date"), version_rule_match.group("source")[:7]
        )
    )
    if evidence.get("candidateBuildId") != version_rule:
        raise DeliveryFailure("V0260_CANDIDATE_BUILD_ID_INVALID")
    source_commit = str(evidence.get("sourceCommit", ""))
    source_prefix = version_rule_match.group("source")
    if (
        re.fullmatch(r"[0-9a-f]{7,40}", source_commit) is None
        or not source_commit.startswith(source_prefix)
    ):
        raise DeliveryFailure("V0260_SOURCE_COMMIT_INVALID")
    if evidence.get("archiveName") != expected_archive_name:
        raise DeliveryFailure("V0260_ARCHIVE_IDENTITY_INVALID")
    if evidence.get("archiveChecksumFile") != expected_archive_name + ".sha256":
        raise DeliveryFailure("V0260_ARCHIVE_CHECKSUM_EVIDENCE_INVALID")
    if evidence.get("acceptanceRecord") != "Issue #120":
        raise DeliveryFailure("V0260_ACCEPTANCE_EVIDENCE_INVALID")
    baseline = manifest.get("baseline", {})
    if (
        baseline.get("requiredProductVersion") != "0.25.3-alpha"
        or baseline.get("sourceStatus") != "candidate"
        or not BASELINE_ARCHIVE_RE.fullmatch(str(baseline.get("archiveName", "")))
        or not SHA256_RE.fullmatch(str(baseline.get("archiveSha256", "")))
    ):
        raise DeliveryFailure("V0260_BASELINE_EVIDENCE_INVALID")
    if "phase1" in json.dumps(manifest, ensure_ascii=False).lower():
        # The legacy path and historical baseline archive are intentionally
        # retained for migration guidance and provenance, not current identity.
        manifest_without_legacy = dict(manifest)
        manifest_without_legacy["installationPolicy"] = {}
        manifest_without_legacy["baseline"] = {}
        if "phase1" in json.dumps(manifest_without_legacy, ensure_ascii=False).lower():
            raise DeliveryFailure("V0260_MANIFEST_LEGACY_IDENTITY")


def audit_prompt_manifest(root: Path, manifest: Dict) -> None:
    relative = manifest["adapter"]["systemPromptManifest"]
    path = root / relative
    prompt_manifest = load_json(path, "V0260_PROMPT_MANIFEST_MISSING")
    if prompt_manifest.get("release") != VERSION:
        raise DeliveryFailure("V0260_PROMPT_RELEASE_INVALID")
    tasks = prompt_manifest.get("tasks", {})
    if not isinstance(tasks, dict) or len(tasks) != 9:
        raise DeliveryFailure("V0260_PROMPT_TASK_COUNT_INVALID")
    for name, item in tasks.items():
        if not isinstance(item, dict):
            raise DeliveryFailure("V0260_PROMPT_ENTRY_INVALID {0}".format(name))
        prompt_path = path.parent / str(item.get("file", ""))
        if not prompt_path.is_file() or sha256(prompt_path) != item.get("sha256"):
            raise DeliveryFailure("V0260_PROMPT_HASH_INVALID {0}".format(name))


def audit_smart_fill_write_contract(root, plugin_root=None, prompt_path=None):
    plugin = Path(plugin_root) if plugin_root is not None else (
        Path(root) / "packages/wps-ai-assistant-et_1.0.0"
    )
    prompt = Path(prompt_path) if prompt_path is not None else (
        Path(root)
        / "packages/adapter-start-kit/adapter_service/system_prompts/excel-smart-fill.md"
    )
    try:
        html = (plugin / "taskpane.html").read_text(encoding="utf-8")
        js = (plugin / "taskpane.js").read_text(encoding="utf-8")
        helpers_js = (plugin / "taskpane-helpers.js").read_text(encoding="utf-8")
        ribbon = (plugin / "ribbon.xml").read_text(encoding="utf-8")
        prompt_text = prompt.read_text(encoding="utf-8")
    except OSError as exc:
        raise DeliveryFailure("V0260_SMART_FILL_WRITE_MISSING") from exc
    if 'id="btnAiExcelSmartFill"' not in ribbon or "智能填写" not in ribbon:
        raise DeliveryFailure("V0260_SMART_FILL_RIBBON_MISSING")
    if "写入内容" not in html or "生成预览" not in html:
        raise DeliveryFailure("V0260_SMART_FILL_WRITE_MISSING")
    if "撤销" in html or "OnUndo" in js or "OnUndo" in helpers_js:
        raise DeliveryFailure("V0260_SMART_FILL_UNDO_PROMISE")
    if "excel.smart_fill.v1" not in prompt_text:
        raise DeliveryFailure("V0260_SMART_FILL_SCHEMA_MISSING")
    if (
        "buildExcelSmartFillReadonlyPreview" not in js
        or "finalizeExcelSmartFillWriteSuccess" not in js
        or "buildExcelSmartFillDefaultSource" not in js
        or "describeExcelSmartFillHostCell" not in js
        or "writeExcelSmartFillCells" not in js
        or "COMPENSATION_FAILED" not in js
        or "COMPENSATION_SUCCEEDED" not in js
        or "内部故障处理" not in js
    ):
        raise DeliveryFailure("V0260_SMART_FILL_WRITE_MISSING")
    if (
        "writeExcelSmartFillCells" not in helpers_js
        or "sameSmartFillSnapshotState" not in helpers_js
        or "smartFillWriteValueMatches" not in helpers_js
        or "COMPENSATION_FAILED" not in helpers_js
        or "COMPENSATION_SUCCEEDED" not in helpers_js
    ):
        raise DeliveryFailure("V0260_SMART_FILL_COMPENSATION_CONTRACT_MISSING")


def audit_installer(root: Path) -> None:
    installer = root / "installer/install_ai_wps.sh"
    content = installer.read_text(encoding="utf-8")
    required_markers = (
        'INSTALL_ROOT="${AI_WPS_INSTALL_ROOT:-$TARGET_HOME/ai-wps}"',
        'LEGACY_PHASE1_INSTALL_ROOT="$TARGET_HOME/ai-wps-phase1"',
        "legacy_phase1_install_detected=true",
        "legacy_phase1_action=read_only",
        "manual_reinstall_required=true",
        "manual_reconfigure_required=true",
        "legacy_runtime_data_migrated=false",
        "legacy_install_deleted=false",
        "ai_wps_install_start=true",
        "ai_wps_install_done=true",
        "preview_path_conflicts_with_legacy",
        "preview_existing_install_manifest_required",
        "preview_existing_install_current_pointer_required",
        "preview_existing_install_release_required",
        "preview_existing_install_manifest_invalid",
    )
    for marker in required_markers:
        if marker not in content:
            raise DeliveryFailure("V0260_INSTALLER_CONTRACT_MISSING {0}".format(marker))
    if "legacy_runtime_state_exists; then" in content or "--legacy-root" in content:
        raise DeliveryFailure("V0260_LEGACY_MIGRATION_ENABLED")
    if 'rm -rf "$LEGACY_PHASE1_INSTALL_ROOT"' in content:
        raise DeliveryFailure("V0260_LEGACY_DELETE_ENABLED")


def audit_lifecycle(root: Path) -> None:
    lifecycle = root / "scripts/python38_delivery_lifecycle_gate.py"
    content = lifecycle.read_text(encoding="utf-8")
    for marker in ("installer/install_ai_wps.sh", "ai_wps_install_done=true"):
        if marker not in content:
            raise DeliveryFailure("V0260_LIFECYCLE_CONTRACT_MISSING {0}".format(marker))
    if any(
        marker in content
        for marker in (
            "install_phase1.sh",
            "phase1_install_done=true",
            "audit_phase1_delivery.py",
        )
    ):
        raise DeliveryFailure("V0260_LIFECYCLE_IDENTITY_INVALID")


def audit_current_identity_references(root: Path) -> None:
    excluded = "scripts/audit_v0260_preview1_delivery.py"
    forbidden = (
        "installer/install_phase1.sh",
        "scripts/phase1_smoke_test.sh",
        "phase1_install_start=true",
        "phase1_install_done=true",
        "phase1_smoke_start=true",
        "phase1_smoke_done=true",
        "Phase 1 WPS AI assistant",
        "Formal Phase 1 WPS AI assistant plugin.",
    )
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.relative_to(root).as_posix() == excluded:
            continue
        if path.suffix.lower() not in {".css", ".html", ".js", ".json", ".md", ".py", ".sh", ".txt", ".xml", ".yml"}:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if any(marker in content for marker in forbidden):
            raise DeliveryFailure(
                "V0260_CURRENT_IDENTITY_LEAK {0}".format(path.relative_to(root).as_posix())
            )


def audit_status(root: Path, manifest: Dict) -> None:
    status = load_json(root / "docs/v0260-preview1-candidate-status.json", "V0260_STATUS_MISSING")
    records = status.get("records")
    evidence = manifest.get("candidateEvidence", {})
    if status.get("version") != VERSION or not isinstance(records, list) or len(records) != 1:
        raise DeliveryFailure("V0260_STATUS_SCHEMA_INVALID")
    record = records[0]
    for key in ("candidateBuildId", "archiveName", "archiveChecksumFile", "sourceCommit"):
        if record.get(key) != evidence.get(key) and not (
            key == "archiveChecksumFile"
            and record.get(key) == evidence.get(key)
        ):
            raise DeliveryFailure("V0260_STATUS_EVIDENCE_MISMATCH {0}".format(key))
    if record.get("status") != "candidate":
        raise DeliveryFailure("V0260_STATUS_NOT_CANDIDATE")


def audit_hashes(root: Path) -> None:
    path = root / "release-file-hashes.json"
    if not path.is_file():
        raise DeliveryFailure("V0260_FILE_HASH_MANIFEST_MISSING")
    hashes = load_json(path, "V0260_FILE_HASH_MANIFEST_INVALID")
    if hashes.get("version") != VERSION or hashes.get("algorithm") != "sha256":
        raise DeliveryFailure("V0260_FILE_HASH_MANIFEST_INVALID")
    actual = delivery_files(root) - {"release-file-hashes.json"}
    expected = hashes.get("files", {})
    if set(expected) != actual:
        raise DeliveryFailure("V0260_FILE_HASH_INVENTORY_MISMATCH")
    for relative, digest in expected.items():
        if not SHA256_RE.fullmatch(str(digest)) or sha256(root / relative) != digest:
            raise DeliveryFailure("V0260_FILE_HASH_MISMATCH {0}".format(relative))


def audit_archive_checksum(
    archive: Path, checksum_file: Path, expected_name: Optional[str]
) -> None:
    if not archive.is_file() or not checksum_file.is_file():
        raise DeliveryFailure("V0260_ARCHIVE_CHECKSUM_MISSING")
    fields = checksum_file.read_text(encoding="utf-8").strip().split()
    if len(fields) != 2 or not SHA256_RE.fullmatch(fields[0]):
        raise DeliveryFailure("V0260_ARCHIVE_CHECKSUM_FORMAT_INVALID")
    if fields[1] != (expected_name or archive.name):
        raise DeliveryFailure("V0260_ARCHIVE_CHECKSUM_NAME_MISMATCH")
    if fields[0] != sha256(archive):
        raise DeliveryFailure("V0260_ARCHIVE_CHECKSUM_MISMATCH")


def audit(root: Path, archive: Optional[Path], checksum_file: Optional[Path], expected_name: Optional[str]) -> None:
    if not root.is_dir():
        raise DeliveryFailure("V0260_DELIVERY_ROOT_MISSING")
    actual = delivery_files(root)
    manifest = load_json(root / "release-manifest.json", "V0260_MANIFEST_MISSING")
    allowlist = load_json(root / "release-allowlist.json", "V0260_ALLOWLIST_MISSING")
    audit_inventory(root, actual, allowlist)
    audit_manifest(root, manifest)
    audit_prompt_manifest(root, manifest)
    audit_smart_fill_write_contract(root)
    audit_installer(root)
    audit_lifecycle(root)
    audit_current_identity_references(root)
    audit_status(root, manifest)
    audit_hashes(root)
    if archive is not None or checksum_file is not None:
        if archive is None or checksum_file is None:
            raise DeliveryFailure("V0260_ARCHIVE_CHECKSUM_PAIR_REQUIRED")
        audit_archive_checksum(archive, checksum_file, expected_name)
    print("v0260_preview1_delivery_audit=passed status=candidate version={0}".format(VERSION))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("delivery_root", type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--checksum-file", type=Path)
    parser.add_argument("--expected-archive-name")
    args = parser.parse_args(argv)
    try:
        audit(
            args.delivery_root.resolve(),
            args.archive.resolve() if args.archive else None,
            args.checksum_file.resolve() if args.checksum_file else None,
            args.expected_archive_name,
        )
    except (DeliveryFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print("v0260_preview1_delivery_audit=failed {0}".format(exc))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
