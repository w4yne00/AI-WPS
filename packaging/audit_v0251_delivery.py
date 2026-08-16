#!/usr/bin/env python3
"""Audit the assembled v0.25.1-alpha Phase1 candidate."""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set


VERSION = "0.25.1-alpha"
BASELINE_VERSION = "0.25.0-alpha"
FORMAT_ASSET_VERSION = "0.25.1-format-rules-alpha"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{7,40}$")
REFERENCE_WORKFLOWS = {
    "reference-workflows/format-semantics-text-v1.yml",
    "reference-workflows/format-semantics-vision-v1.yml",
}
FORBIDDEN_SCOPE_PARTS = {"material_composer", "adr-0116", "d-0001", "adr-0117"}


class DeliveryFailure(RuntimeError):
    pass


def load_json(path: Path, code: str) -> Dict:
    if not path.is_file():
        raise DeliveryFailure(code)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DeliveryFailure(code)
    return value


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit_archive_checksum(archive: Path, checksum_file: Path) -> None:
    if not archive.is_file() or not checksum_file.is_file():
        raise DeliveryFailure("V0251_ARCHIVE_CHECKSUM_FILE_MISSING")
    fields = checksum_file.read_text(encoding="utf-8").strip().split()
    if len(fields) != 2 or not SHA256_RE.fullmatch(fields[0]):
        raise DeliveryFailure("V0251_ARCHIVE_CHECKSUM_FORMAT_INVALID")
    if fields[1] != archive.name:
        raise DeliveryFailure("V0251_ARCHIVE_CHECKSUM_NAME_MISMATCH")
    if fields[0] != sha256(archive):
        raise DeliveryFailure("V0251_ARCHIVE_CHECKSUM_MISMATCH")


def safe_path(root: Path, value: str, code: str) -> Path:
    path = Path(value)
    if not value or path.is_absolute() or ".." in path.parts or "\\" in value:
        raise DeliveryFailure("{0} {1}".format(code, value))
    target = root / path
    if not target.is_file():
        raise DeliveryFailure("{0} {1}".format(code, value))
    return target


def audit_format_assets(root: Path, manifest: Dict) -> None:
    assets = load_json(root / "format-rule-assets-manifest.json", "FORMAT_ASSETS_MANIFEST_MISSING")
    if assets.get("version") != FORMAT_ASSET_VERSION or assets.get("deliveryVersion") != VERSION:
        raise DeliveryFailure("FORMAT_ASSETS_VERSION_INVALID")
    rule_pack_path = safe_path(root, assets.get("rulePack", ""), "FORMAT_RULE_PACK_REFERENCE_INVALID")
    notice_path = safe_path(root, assets.get("algorithm", {}).get("notice", ""), "THIRD_PARTY_NOTICE_REFERENCE_INVALID")
    gate_path = safe_path(root, assets.get("python", {}).get("compatibilityGate", ""), "PYTHON38_GATE_REFERENCE_INVALID")
    if "THIRD_PARTY_NOTICES" not in notice_path.name or not gate_path.name.endswith("check_python38_compatibility.py"):
        raise DeliveryFailure("FORMAT_ASSETS_REFERENCE_INVALID")
    rule_pack = load_json(rule_pack_path, "FORMAT_RULE_PACK_MISSING")
    algorithm = rule_pack.get("algorithm", {})
    if algorithm.get("writeBack") is not False or "defaultTemplateValues" in algorithm:
        raise DeliveryFailure("FORMAT_RULE_PACK_WRITEBACK_OR_DEFAULTS_ENABLED")
    algorithm_path = safe_path(root, algorithm.get("adapterPath", ""), "FORMAT_ALGORITHM_REFERENCE_INVALID")
    source_manifest_path = safe_path(root, algorithm.get("sourceManifest", ""), "FORMAT_SOURCE_MANIFEST_REFERENCE_INVALID")
    if not SHA256_RE.fullmatch(str(algorithm.get("adapterSha256", ""))) or sha256(algorithm_path) != algorithm["adapterSha256"]:
        raise DeliveryFailure("FORMAT_ALGORITHM_HASH_MISMATCH")
    if not SHA256_RE.fullmatch(str(algorithm.get("sourceManifestSha256", ""))) or sha256(source_manifest_path) != algorithm["sourceManifestSha256"]:
        raise DeliveryFailure("FORMAT_SOURCE_MANIFEST_HASH_MISMATCH")
    references = manifest.get("formatReview", {}).get("referenceWorkflows", [])
    if set(references) != REFERENCE_WORKFLOWS:
        raise DeliveryFailure("FORMAT_REFERENCE_WORKFLOW_SET_INVALID")
    for relative in sorted(REFERENCE_WORKFLOWS):
        workflow = safe_path(root, relative, "FORMAT_REFERENCE_WORKFLOW_MISSING")
        content = workflow.read_text(encoding="utf-8")
        if "contract_version: format_semantics.v1" not in content or "variable: result_json" not in content:
            raise DeliveryFailure("FORMAT_REFERENCE_WORKFLOW_CONTRACT_INVALID")
        if any(token in content.lower() for token in ("api_key", "apikey", "providerbaseurl", "servicebaseurl", "http://", "https://")):
            raise DeliveryFailure("FORMAT_REFERENCE_WORKFLOW_SECRET_OR_ADDRESS")
        expected = (
            "ffe15d87ff293b82c39b5865f9299f9c857a8662738ef8e9e6b4ec31f4bca1c3"
            if relative.endswith("text-v1.yml")
            else "ac2324e4620e4d945046745ac660393a9a51827796c902cc65ebc3ab49d52ec4"
        )
        if sha256(workflow) != expected:
            raise DeliveryFailure("FORMAT_REFERENCE_WORKFLOW_HASH_MISMATCH")


def audit_visual_default(root: Path, manifest: Dict) -> None:
    visual = manifest.get("visualPolicy", {})
    if visual.get("enabledByDefault") is not False:
        raise DeliveryFailure("VISUAL_DEFAULT_MUST_BE_CLOSED")
    for key in ("pixelExportWhenDisabled", "pixelUploadWhenDisabled", "imageSlotAllocationWhenDisabled"):
        if visual.get(key) is not False:
            raise DeliveryFailure("VISUAL_SIDE_EFFECT_DEFAULT_MUST_BE_CLOSED {0}".format(key))
    config = load_json(root / "packages/adapter-start-kit/config/adapter.example.json", "ADAPTER_EXAMPLE_CONFIG_MISSING")
    image = config.get("formatReview", {}).get("imageSemantics", {})
    if image.get("enabled") is not False or image.get("wpsAcceptanceConfirmed") is not False:
        raise DeliveryFailure("IMAGE_SEMANTICS_EXAMPLE_NOT_CLOSED")
    adapter_root = root / "packages/adapter-start-kit/adapter_service"
    sys.path.insert(0, str(adapter_root))
    from app.services.word.image_semantics import collect_image_inventory, image_pixel_policy

    policy = image_pixel_policy(
        {"enabled": False, "wpsAcceptanceConfirmed": False},
        {"imageInputMode": "openai_image_url", "serviceBaseUrl": "https://example.invalid/v1"},
    )
    inventory = collect_image_inventory({"images": [{"imageId": "fixture", "captionStatus": "missing"}]})
    if policy.get("allowed") is not False or inventory.get("pixelExportCount") != 0 or inventory.get("pixelUploadCount") != 0:
        raise DeliveryFailure("VISUAL_CLOSED_SIDE_EFFECT_CONTRACT_FAILED")


def plugin_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.glob("packages/wps-ai-assistant*/*")):
        if path.is_file() and path.suffix.lower() in {".html", ".js", ".json"}:
            yield path


def audit_plugin_cache_identity(root: Path, expected_version: str) -> None:
    manifests = sorted(root.glob("packages/wps-ai-assistant*/manifest.json"))
    expected_directories = {
        "wps-ai-assistant_1.0.0",
        "wps-ai-assistant-wpp_1.0.0",
        "wps-ai-assistant-et_1.0.0",
    }
    if {path.parent.name for path in manifests} != expected_directories:
        raise DeliveryFailure("PLUGIN_MANIFEST_COUNT_INVALID")
    for manifest_path in manifests:
        manifest = load_json(manifest_path, "PLUGIN_MANIFEST_INVALID")
        if manifest.get("version") != expected_version:
            raise DeliveryFailure("PLUGIN_VERSION_MISMATCH {0}".format(manifest_path.parent.name))
    seen_version = False
    for path in plugin_files(root):
        content = path.read_text(encoding="utf-8")
        if "0.23.1-alpha" in content or "0.25.0-alpha" in content:
            raise DeliveryFailure("PLUGIN_CACHE_OLD_VERSION {0}".format(path.name))
        if expected_version in content:
            seen_version = True
    if not seen_version:
        raise DeliveryFailure("PLUGIN_CACHE_VERSION_MISSING")


def audit_scope(actual: Set[str]) -> None:
    for relative in actual:
        normalized = relative.lower()
        if any(part in normalized for part in FORBIDDEN_SCOPE_PARTS):
            raise DeliveryFailure("FUTURE_SCOPE_ASSET_REJECTED {0}".format(relative))
        if "/preview" in normalized or normalized.startswith("preview/"):
            raise DeliveryFailure("PREVIEW_ASSET_REJECTED {0}".format(relative))


def audit(root: Path) -> None:
    manifest = load_json(root / "release-manifest.json", "RELEASE_MANIFEST_MISSING")
    allowlist = load_json(root / "release-allowlist.json", "RELEASE_ALLOWLIST_MISSING")
    if manifest.get("version") != VERSION or manifest.get("adapter", {}).get("version") != VERSION:
        raise DeliveryFailure("V0251_VERSION_MISMATCH")
    if allowlist.get("version") != VERSION:
        raise DeliveryFailure("V0251_ALLOWLIST_VERSION_MISMATCH")
    baseline = manifest.get("baseline", {})
    if baseline.get("acceptedVersion") != BASELINE_VERSION or baseline.get("sourceStatus") != "candidate":
        raise DeliveryFailure("V0250_CANDIDATE_BASELINE_REQUIRED")
    evidence = manifest.get("candidateEvidence", {})
    if not COMMIT_RE.fullmatch(str(evidence.get("sourceCommit", ""))):
        raise DeliveryFailure("V0251_SOURCE_COMMIT_MISSING")
    release_date = str(manifest.get("releaseDate", ""))
    if not re.fullmatch(r"[0-9]{8}", release_date):
        raise DeliveryFailure("V0251_RELEASE_DATE_INVALID")
    expected_checksum_name = "ai-wps-phase1-delivery-{0}-v0251.tar.gz.sha256".format(
        release_date
    )
    if evidence.get("archiveChecksumFile") != expected_checksum_name:
        raise DeliveryFailure("V0251_ARCHIVE_CHECKSUM_EVIDENCE_MISSING")
    if manifest.get("targetAcceptanceIssue") != 59 or manifest.get("targetAcceptance", {}).get("status") != "manual-pending":
        raise DeliveryFailure("ISSUE_59_MANUAL_ACCEPTANCE_REQUIRED")
    policy = manifest.get("deliveryPolicy", {})
    if (
        policy.get("status") != "candidate"
        or policy.get("auditScript") != "scripts/audit_delivery.py"
        or policy.get("candidateAuditScript") != "scripts/audit_v0251_delivery.py"
    ):
        raise DeliveryFailure("V0251_CANDIDATE_POLICY_INVALID")
    if manifest.get("formatReview", {}).get("enabledByDefault") is not False:
        raise DeliveryFailure("FORMAT_REVIEW_DEFAULT_MUST_BE_CLOSED")
    note = safe_path(root, "docs/v0251-delivery.md", "V0251_CANDIDATE_NOTE_MISSING")
    note_content = note.read_text(encoding="utf-8")
    for required in (
        "v0.25.1-alpha",
        "ai-wps-phase1-delivery-<YYYYMMDD>-v0251.tar.gz",
        "Issue #59",
        "format_semantics.v1",
        "manual acceptance",
    ):
        if required not in note_content:
            raise DeliveryFailure("V0251_CANDIDATE_NOTE_INCOMPLETE {0}".format(required))
    actual = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
    audit_scope(actual)
    audit_plugin_cache_identity(root, VERSION)
    audit_format_assets(root, manifest)
    audit_visual_default(root, manifest)
    print("v0251_delivery_audit=passed status=candidate version={0}".format(VERSION))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("delivery_root", type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--checksum-file", type=Path)
    args = parser.parse_args(argv)
    try:
        if (args.archive is None) != (args.checksum_file is None):
            raise DeliveryFailure("V0251_ARCHIVE_CHECKSUM_ARGUMENTS_INCOMPLETE")
        audit(args.delivery_root.resolve())
        if args.archive is not None and args.checksum_file is not None:
            audit_archive_checksum(args.archive.resolve(), args.checksum_file.resolve())
    except (DeliveryFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print("v0251_delivery_audit=failed {0}".format(exc))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
