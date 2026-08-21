#!/usr/bin/env python3
"""Audit the assembled v0.25.0 final delivery candidate."""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional


VERSION = "0.25.0-alpha"
BASELINE_VERSION = "0.24.0-alpha"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REFERENCE_WORKFLOWS = {
    "reference-workflows/format-semantics-text-v1.yml",
    "reference-workflows/format-semantics-vision-v1.yml",
}


class DeliveryFailure(RuntimeError):
    pass


LEGACY_FORMAT_MARKERS = (
    "general-office",
    "technical-file-format-requirements",
    "technical-file-structure-rules",
    "templates/company/technical-file-",
)
AUDIT_SCRIPT_NAMES = {
    "audit_format_rule_assets.py",
    "audit_v0250_delivery.py",
    "audit_v0251_delivery.py",
}


def load_json(path: Path, code: str) -> Dict:
    if not path.is_file():
        raise DeliveryFailure(code)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DeliveryFailure(code)
    return value


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit_no_legacy_format_references(root: Path) -> None:
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".css", ".html", ".js", ".json", ".md", ".py", ".sh", ".txt", ".xml", ".yml"}:
            continue
        if path.name in AUDIT_SCRIPT_NAMES and path.parent.name == "scripts":
            continue
        content = path.read_text(encoding="utf-8")
        if any(marker in content for marker in LEGACY_FORMAT_MARKERS):
            raise DeliveryFailure("LEGACY_FORMAT_REFERENCE {0}".format(path.relative_to(root)))
        if path.relative_to(root).as_posix().startswith("packages/adapter-start-kit/templates/"):
            raise DeliveryFailure("HISTORICAL_TEMPLATE_ASSET_DELIVERED")


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
    if assets.get("version") != "0.25.0-format-rules-alpha" or assets.get("deliveryVersion") != VERSION:
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
    algorithm_path = safe_path(
        root,
        algorithm.get("adapterPath", ""),
        "FORMAT_ALGORITHM_REFERENCE_INVALID",
    )
    source_template_path = algorithm_path.parent / "assets/wx_template.docx"
    if not source_template_path.is_file():
        raise DeliveryFailure("FORMAT_TEMPLATE_SOURCE_MISSING")
    source_manifest_path = safe_path(
        root,
        algorithm.get("sourceManifest", ""),
        "FORMAT_SOURCE_MANIFEST_REFERENCE_INVALID",
    )
    source_classification_path = safe_path(
        root,
        algorithm.get("sourceClassification", ""),
        "FORMAT_SOURCE_CLASSIFICATION_REFERENCE_INVALID",
    )
    if not SHA256_RE.fullmatch(str(algorithm.get("adapterSha256", ""))) or sha256(algorithm_path) != algorithm["adapterSha256"]:
        raise DeliveryFailure("FORMAT_ALGORITHM_HASH_MISMATCH")
    if not SHA256_RE.fullmatch(str(algorithm.get("sourceManifestSha256", ""))) or sha256(source_manifest_path) != algorithm["sourceManifestSha256"]:
        raise DeliveryFailure("FORMAT_SOURCE_MANIFEST_HASH_MISMATCH")
    if not SHA256_RE.fullmatch(str(algorithm.get("sourceClassificationSha256", ""))) or sha256(source_classification_path) != algorithm["sourceClassificationSha256"]:
        raise DeliveryFailure("FORMAT_SOURCE_CLASSIFICATION_HASH_MISMATCH")
    if sha256(source_template_path) != rule_pack.get("template", {}).get("sourceDocumentSha256"):
        raise DeliveryFailure("FORMAT_TEMPLATE_SOURCE_HASH_MISMATCH")
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
        if sha256(workflow) != ("ffe15d87ff293b82c39b5865f9299f9c857a8662738ef8e9e6b4ec31f4bca1c3" if relative.endswith("text-v1.yml") else "ac2324e4620e4d945046745ac660393a9a51827796c902cc65ebc3ab49d52ec4"):
            raise DeliveryFailure("FORMAT_REFERENCE_WORKFLOW_HASH_MISMATCH")


def audit_visual_default(root: Path, manifest: Dict) -> None:
    visual = manifest.get("visualPolicy", {})
    if visual.get("enabledByDefault") is not False:
        raise DeliveryFailure("VISUAL_DEFAULT_MUST_BE_CLOSED")
    for key in ("pixelExportWhenDisabled", "pixelUploadWhenDisabled", "imageSlotAllocationWhenDisabled"):
        if visual.get(key) is not False:
            raise DeliveryFailure("VISUAL_SIDE_EFFECT_DEFAULT_MUST_BE_CLOSED {0}".format(key))
    config = load_json(
        root / "packages/adapter-start-kit/config/adapter.example.json",
        "ADAPTER_EXAMPLE_CONFIG_MISSING",
    )
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
    inventory = collect_image_inventory(
        {"images": [{"imageId": "fixture", "captionStatus": "missing"}]}
    )
    if policy.get("allowed") is not False or inventory.get("pixelExportCount") != 0 or inventory.get("pixelUploadCount") != 0:
        raise DeliveryFailure("VISUAL_CLOSED_SIDE_EFFECT_CONTRACT_FAILED")


def audit(root: Path) -> None:
    manifest = load_json(root / "release-manifest.json", "RELEASE_MANIFEST_MISSING")
    allowlist = load_json(root / "release-allowlist.json", "RELEASE_ALLOWLIST_MISSING")
    if manifest.get("version") != VERSION or manifest.get("adapter", {}).get("version") != VERSION:
        raise DeliveryFailure("V0250_VERSION_MISMATCH")
    if allowlist.get("version") != VERSION:
        raise DeliveryFailure("V0250_ALLOWLIST_VERSION_MISMATCH")
    baseline = manifest.get("baseline", {})
    if (
        baseline.get("acceptedVersion") != BASELINE_VERSION
        or baseline.get("acceptanceIssue") != 42
        or baseline.get("acceptanceStateRequired") != "closed"
    ):
        raise DeliveryFailure("V0240_ACCEPTED_BASELINE_REQUIRED")
    if not SHA256_RE.fullmatch(str(baseline.get("archiveSha256", ""))):
        raise DeliveryFailure("V0240_BASELINE_HASH_MISSING")
    if manifest.get("deliveryPolicy", {}).get("status") != "candidate":
        raise DeliveryFailure("V0250_CANDIDATE_STATUS_REQUIRED")
    if manifest.get("formatReview", {}).get("enabledByDefault") is not False:
        raise DeliveryFailure("FORMAT_REVIEW_DEFAULT_MUST_BE_CLOSED")
    audit_format_assets(root, manifest)
    audit_visual_default(root, manifest)
    audit_no_legacy_format_references(root)
    print("v0250_delivery_audit=passed status=candidate version={0}".format(VERSION))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("delivery_root", type=Path)
    args = parser.parse_args(argv)
    try:
        audit(args.delivery_root.resolve())
    except (DeliveryFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print("v0250_delivery_audit=failed {0}".format(exc))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
