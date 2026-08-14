#!/usr/bin/env python3
"""Finalize the assembled tree as a versioned v0.25.0 candidate package."""

import argparse
import copy
import hashlib
import json
import tarfile
from pathlib import Path
from typing import Iterable, List, Optional, Tuple


VERSION = "0.25.0-alpha"
BASELINE_VERSION = "0.24.0-alpha"
TEXT_SUFFIXES = {".css", ".html", ".js", ".json", ".md", ".py", ".sh", ".txt", ".xml", ".yml"}


def candidate_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES:
            yield path


def rewrite_versions(root: Path, versions: Tuple[str, ...]) -> List[str]:
    changed = []
    for path in candidate_files(root):
        text = path.read_text(encoding="utf-8")
        updated = text
        for old_version in versions:
            updated = updated.replace(old_version, VERSION)
        if updated != text:
            path.write_text(updated, encoding="utf-8")
            changed.append(path.relative_to(root).as_posix())
    return changed


def baseline_metadata(archive: Path, expected_version: str) -> dict:
    if not archive.is_file():
        raise ValueError("V0240_BASELINE_ARCHIVE_MISSING")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    try:
        with tarfile.open(str(archive), "r:gz") as handle:
            manifest_member = next(
                member
                for member in handle.getmembers()
                if Path(member.name).name == "release-manifest.json" and member.isfile()
            )
            extracted = handle.extractfile(manifest_member)
            if extracted is None:
                raise ValueError("V0240_BASELINE_MANIFEST_UNREADABLE")
            manifest = json.loads(extracted.read().decode("utf-8"))
    except (OSError, tarfile.TarError, StopIteration, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("V0240_BASELINE_ARCHIVE_INVALID") from exc
    if manifest.get("version") != expected_version:
        raise ValueError("V0240_BASELINE_VERSION_INVALID")
    if manifest.get("deliveryPolicy", {}).get("status") != "candidate":
        raise ValueError("V0240_BASELINE_NOT_CANDIDATE")
    return {
        "acceptedVersion": expected_version,
        "archiveSha256": digest,
        "archiveName": archive.name,
    }


def update_format_assets_manifest(root: Path) -> None:
    path = root / "format-rule-assets-manifest.json"
    if not path.is_file():
        raise ValueError("FORMAT_RULE_ASSETS_MANIFEST_MISSING")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["rulePack"] = (
        "packages/adapter-start-kit/adapter_service/format_rule_packs/"
        "technical-file-format-requirements.v2026-05-23.json"
    )
    manifest.setdefault("algorithm", {})["notice"] = (
        "packages/adapter-start-kit/adapter_service/vendor/"
        "wx_doc_format_algorithm/THIRD_PARTY_NOTICES.md"
    )
    manifest.setdefault("python", {})["compatibilityGate"] = (
        "scripts/check_python38_compatibility.py"
    )
    manifest["deliveryVersion"] = VERSION
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    rule_pack_path = root / manifest["rulePack"]
    rule_pack = json.loads(rule_pack_path.read_text(encoding="utf-8"))
    algorithm = rule_pack.setdefault("algorithm", {})
    algorithm["adapterPath"] = (
        "packages/adapter-start-kit/adapter_service/vendor/"
        "wx_doc_format_algorithm/algorithm.py"
    )
    algorithm["sourceManifest"] = (
        "packages/adapter-start-kit/adapter_service/vendor/"
        "wx_doc_format_algorithm/SOURCE_MANIFEST.json"
    )
    canonical = copy.deepcopy(rule_pack)
    canonical.pop("integrity", None)
    rule_pack.setdefault("integrity", {})["contentSha256"] = hashlib.sha256(
        json.dumps(
            canonical,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    rule_pack_path.write_text(json.dumps(rule_pack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def prepare(
    root: Path,
    date_tag: str,
    baseline_archive: Path,
    baseline_version: str = BASELINE_VERSION,
    acceptance_issue: int = 42,
) -> None:
    if baseline_version != BASELINE_VERSION:
        raise ValueError("V0240_BASELINE_VERSION_REQUIRED")
    if not date_tag or len(date_tag) != 8 or not date_tag.isdigit():
        raise ValueError("V0250_DATE_INVALID")
    baseline = baseline_metadata(baseline_archive, baseline_version)
    rewrite_versions(root, ("0.23.1-alpha", "0.24.0-alpha"))

    manifest_path = root / "release-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["version"] = VERSION
    manifest["releaseDate"] = date_tag
    manifest["versionRule"] = "AI-WPS-P1-WORD-EXCEL-PPT-0.25.0-" + date_tag
    manifest["deliveryPolicy"] = {
        "status": "candidate",
        "sourceAssembly": "explicit-allowlist",
        "allowlist": "release-allowlist.json",
        "fileHashes": "release-file-hashes.json",
        "auditScript": "scripts/audit_delivery.py",
        "lifecycleGate": "scripts/python38_delivery_lifecycle_gate.py",
        "targetAcceptanceRequired": True,
    }
    manifest["baseline"] = dict(baseline)
    manifest["baseline"].update(
        {
            "acceptanceIssue": acceptance_issue,
            "acceptanceStateRequired": "closed",
        }
    )
    manifest["formatReview"] = {
        "enabledByDefault": False,
        "featureSwitch": "AI_WPS_ENABLE_DETERMINISTIC_FORMAT_REVIEW",
        "rulePackManifest": "format-rule-assets-manifest.json",
        "referenceWorkflows": [
            "reference-workflows/format-semantics-text-v1.yml",
            "reference-workflows/format-semantics-vision-v1.yml",
        ],
    }
    manifest["visualPolicy"] = {
        "enabledByDefault": False,
        "runtimeMasterSwitch": "formatReview.imageSemantics.enabled",
        "requiresWpsAcceptance": True,
        "pixelExportWhenDisabled": False,
        "pixelUploadWhenDisabled": False,
        "imageSlotAllocationWhenDisabled": False,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    allowlist_path = root / "release-allowlist.json"
    allowlist = json.loads(allowlist_path.read_text(encoding="utf-8"))
    allowlist["version"] = VERSION
    allowlist_path.write_text(json.dumps(allowlist, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    prompt_path = root / manifest["adapter"]["systemPromptManifest"]
    prompt_manifest = json.loads(prompt_path.read_text(encoding="utf-8"))
    prompt_manifest["release"] = VERSION
    prompt_path.write_text(json.dumps(prompt_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    update_format_assets_manifest(root)
    print("v0250_delivery_prepared=passed version={0}".format(VERSION))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--date", required=True)
    parser.add_argument("--baseline-archive", required=True, type=Path)
    parser.add_argument("--baseline-version", default=BASELINE_VERSION)
    parser.add_argument("--acceptance-issue", required=True, type=int)
    args = parser.parse_args(argv)
    try:
        prepare(
            args.root.resolve(),
            args.date,
            args.baseline_archive.resolve(),
            args.baseline_version,
            args.acceptance_issue,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print("v0250_delivery_prepared=failed {0}".format(exc))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
