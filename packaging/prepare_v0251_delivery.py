#!/usr/bin/env python3
"""Finalize the assembled tree as a versioned v0.25.1 candidate package."""

import argparse
import copy
from datetime import datetime
import hashlib
import json
import re
import tarfile
from pathlib import Path
from typing import Iterable, List, Optional, Tuple


VERSION = "0.25.1-alpha"
BASELINE_VERSION = "0.25.0-alpha"
FORMAT_ASSET_VERSION = "0.25.1-format-rules-alpha"
TEXT_SUFFIXES = {".css", ".html", ".js", ".json", ".md", ".py", ".sh", ".txt", ".xml", ".yml"}
SOURCE_COMMIT_RE = re.compile(r"^[0-9a-f]{7,40}$")
CANDIDATE_ARCHIVE_RE = re.compile(
    r"^ai-wps-phase1-delivery-(?P<date>[0-9]{8})"
    r"(?:-(?P<source>[0-9a-f]{7}))?-v0251\.tar\.gz$"
)
PREVIOUS_BUILD_ID_RE = re.compile(
    r"^AI-WPS-P1-WORD-EXCEL-PPT-0\.25\.1-[0-9]{8}(?:-[0-9a-f]{7,40})?$"
)
VERSION_REWRITE_EXCLUDED_PATHS = {
    "README.md",
    "docs/v0251-delivery.md",
    "scripts/audit_delivery.py",
    "scripts/audit_v0251_delivery.py",
    "scripts/python38_delivery_lifecycle_gate.py",
    "scripts/python38_delivery_runtime_gate.py",
}
STATUS_RELATIVE_PATH = "docs/v0251-candidate-status.json"
TARGET_ACCEPTANCE_RELATIVE_PATH = "docs/v0251-target-machine-acceptance.md"
TARGET_ACCEPTANCE_MATRIX_MARKERS = (
    "`OutlineLevel=0`",
    "`OutlineLevel=10`",
    "`OutlineLevel=1..9`",
    "`表格/嵌套表格`",
    "`图片元数据`",
    "`非 BMP emoji`",
    "`dataStatus=insufficient`",
    "其它 `dataStatus`",
)


def candidate_archive_name(date_tag: str, source_commit: str) -> str:
    return "ai-wps-phase1-delivery-{0}-{1}-v0251.tar.gz".format(
        date_tag, source_commit[:7]
    )


def candidate_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES:
            yield path


def rewrite_versions(root: Path, versions: Tuple[str, ...]) -> List[str]:
    changed = []
    for path in candidate_files(root):
        if path.relative_to(root).as_posix() in VERSION_REWRITE_EXCLUDED_PATHS:
            continue
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
        raise ValueError("V0250_BASELINE_ARCHIVE_MISSING")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    try:
        with tarfile.open(str(archive), "r:gz") as handle:
            member = next(
                item
                for item in handle.getmembers()
                if Path(item.name).name == "release-manifest.json" and item.isfile()
            )
            extracted = handle.extractfile(member)
            if extracted is None:
                raise ValueError("V0250_BASELINE_MANIFEST_UNREADABLE")
            manifest = json.loads(extracted.read().decode("utf-8"))
    except (OSError, tarfile.TarError, StopIteration, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("V0250_BASELINE_ARCHIVE_INVALID") from exc
    if manifest.get("version") != expected_version:
        raise ValueError("V0250_BASELINE_VERSION_INVALID")
    if manifest.get("deliveryPolicy", {}).get("status") != "candidate":
        raise ValueError("V0250_BASELINE_NOT_CANDIDATE")
    return {
        "acceptedVersion": expected_version,
        "archiveSha256": digest,
        "archiveName": archive.name,
        "sourceStatus": "candidate",
    }


def previous_candidate_metadata(archive: Path) -> dict:
    match = CANDIDATE_ARCHIVE_RE.fullmatch(archive.name)
    if not archive.is_file():
        raise ValueError("V0251_PREVIOUS_CANDIDATE_ARCHIVE_MISSING")
    if match is None:
        raise ValueError("V0251_PREVIOUS_CANDIDATE_ARCHIVE_NAME_INVALID")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    try:
        with tarfile.open(str(archive), "r:gz") as handle:
            member = next(
                item
                for item in handle.getmembers()
                if Path(item.name).name == "release-manifest.json" and item.isfile()
            )
            extracted = handle.extractfile(member)
            if extracted is None:
                raise ValueError("V0251_PREVIOUS_CANDIDATE_MANIFEST_UNREADABLE")
            manifest = json.loads(extracted.read().decode("utf-8"))
    except (OSError, tarfile.TarError, StopIteration, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("V0251_PREVIOUS_CANDIDATE_ARCHIVE_INVALID") from exc
    if manifest.get("version") != VERSION:
        raise ValueError("V0251_PREVIOUS_CANDIDATE_VERSION_INVALID")
    if manifest.get("releaseDate") != match.group("date"):
        raise ValueError("V0251_PREVIOUS_CANDIDATE_DATE_MISMATCH")
    if manifest.get("deliveryPolicy", {}).get("status") != "candidate":
        raise ValueError("V0251_PREVIOUS_CANDIDATE_NOT_CANDIDATE")
    candidate_evidence = manifest.get("candidateEvidence", {})
    build_id = candidate_evidence.get("candidateBuildId") or manifest.get("versionRule")
    if not isinstance(build_id, str) or not PREVIOUS_BUILD_ID_RE.fullmatch(build_id):
        raise ValueError("V0251_PREVIOUS_CANDIDATE_BUILD_ID_MISSING")
    return {
        "candidateBuildId": build_id,
        "archiveName": archive.name,
        "archiveSha256": digest,
        "status": "rejected",
    }


def record_candidate_lineage(
    root: Path,
    previous: dict,
    date_tag: str,
    source_commit: str,
    current_build_id: str,
    checksum_name: str,
) -> None:
    path = root / STATUS_RELATIVE_PATH
    if not path.is_file():
        raise ValueError("V0251_CANDIDATE_STATUS_MISSING")
    status = json.loads(path.read_text(encoding="utf-8"))
    if (
        status.get("schemaVersion") != 1
        or status.get("product") != "AI-WPS"
        or status.get("version") != VERSION
        or not isinstance(status.get("records"), list)
    ):
        raise ValueError("V0251_CANDIDATE_STATUS_INVALID")
    previous_records = [
        item
        for item in status["records"]
        if isinstance(item, dict) and item.get("archiveName") == previous["archiveName"]
    ]
    if len(previous_records) != 1:
        raise ValueError("V0251_PREVIOUS_CANDIDATE_STATUS_MISSING")
    previous_record = previous_records[0]
    if (
        previous_record.get("status") != "rejected"
        or previous_record.get("archiveSha256") != previous["archiveSha256"]
    ):
        raise ValueError("V0251_PREVIOUS_CANDIDATE_STATUS_INVALID")
    current_record = {
        "candidateBuildId": current_build_id,
        "archiveName": candidate_archive_name(date_tag, source_commit),
        "archiveChecksumFile": checksum_name,
        "sourceCommit": source_commit,
        "status": "candidate",
    }
    status["records"] = [
        item
        for item in status["records"]
        if not (
            isinstance(item, dict)
            and item.get("candidateBuildId") == current_build_id
        )
    ] + [current_record]
    path.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def remove_previous_candidate_identity(root: Path) -> None:
    old_paths = {"docs/v0250-delivery.md", "scripts/audit_v0250_delivery.py"}
    for relative in old_paths:
        path = root / relative
        if path.is_file():
            path.unlink()
    allowlist_path = root / "release-allowlist.json"
    if allowlist_path.is_file():
        allowlist = json.loads(allowlist_path.read_text(encoding="utf-8"))
        allowlist["files"] = [
            item for item in allowlist.get("files", []) if item not in old_paths
        ]
        allowlist_path.write_text(
            json.dumps(allowlist, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def update_format_assets_manifest(root: Path) -> None:
    path = root / "format-rule-assets-manifest.json"
    if not path.is_file():
        raise ValueError("FORMAT_RULE_ASSETS_MANIFEST_MISSING")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["version"] = FORMAT_ASSET_VERSION
    manifest["deliveryVersion"] = VERSION
    manifest["rulePack"] = (
        "packages/adapter-start-kit/adapter_service/format_rule_packs/"
        "technical-document-template-rules.v1.0.0.json"
    )
    manifest.setdefault("algorithm", {})["notice"] = (
        "packages/adapter-start-kit/adapter_service/vendor/"
        "wx_doc_format_algorithm/THIRD_PARTY_NOTICES.md"
    )
    manifest.setdefault("python", {})["compatibilityGate"] = (
        "scripts/check_python38_compatibility.py"
    )
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
    algorithm["sourceClassification"] = (
        "packages/adapter-start-kit/adapter_service/vendor/"
        "wx_doc_format_algorithm/RULE_CLASSIFICATION.json"
    )
    canonical = copy.deepcopy(rule_pack)
    canonical.pop("integrity", None)
    rule_pack.setdefault("integrity", {})["contentSha256"] = hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    rule_pack_path.write_text(
        json.dumps(rule_pack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def write_candidate_delivery_note(
    root: Path,
    date_tag: str,
    source_commit: str,
    candidate_build_id: str,
    archive_name: str,
    checksum_name: str,
    acceptance_issue: int,
) -> None:
    """Generate the package note from the finalized candidate identity."""
    note_path = root / "docs/v0251-delivery.md"
    if not note_path.parent.is_dir():
        raise ValueError("V0251_CANDIDATE_NOTE_DIRECTORY_MISSING")
    note = """# v0.25.1-alpha candidate delivery note

This file is generated by `prepare_v0251_delivery.py` from the assembled
candidate identity. It is not a source-tree build placeholder.

- Candidate label: `{date_tag}-{short_source}`
- Candidate build ID: `{candidate_build_id}`
- Source commit: `{source_commit}`
- Archive name: `{archive_name}`
- Archive checksum file: `{checksum_name}`
- Archive naming template: `ai-wps-phase1-delivery-<YYYYMMDD>-<SOURCE_COMMIT>-v0251.tar.gz`
- Automated status: `candidate`
- Target acceptance status: `manual-pending` (Issue #{acceptance_issue})

The package uses the accepted `v0.25.0-alpha` Phase1 baseline and explicit
allowlist assembly. The v2 deterministic format-review contract is
`word.format_review.snapshot.v2`; JavaScript and Python independently verify
`characterCount`, `contentSha256`, `structureSha256`, and `formatSha256`.
The contract uses `format_semantics.v1` rule assets, UTF-16 character counts,
stable compact JSON, and fail-closed trust-boundary checks. A successful
automated gate records only `candidate`; it is not manual acceptance.

The retired synchronous route `POST /word/format-review` must return
`410 WORD_FORMAT_REVIEW_SYNC_RETIRED` without running a review. Format/hash,
OutlineLevel, table/nested-table, cell-format, image metadata and non-BMP
emoji checks run only through the v2 snapshot/batch/job backend path. Image
semantics remain disabled: no pixel export, upload, or slot allocation is
allowed when the switch is closed.

## Issue #{acceptance_issue} manual acceptance

Manual acceptance remains `manual-pending` until the Kylin V10 ARM64, target
WPS and real-model checks are independently evidenced. The record must remain
pending for any missing, blocked, failed, or unverified item; automated
delivery, static audit, and lifecycle gates cannot close Issue #{acceptance_issue}.
""".format(
        date_tag=date_tag,
        short_source=source_commit[:7],
        candidate_build_id=candidate_build_id,
        source_commit=source_commit,
        archive_name=archive_name,
        checksum_name=checksum_name,
        acceptance_issue=acceptance_issue,
    )
    note_path.write_text(note, encoding="utf-8")


def write_target_machine_acceptance_record(
    root: Path,
    source_commit: str,
    candidate_build_id: str,
    archive_name: str,
    checksum_name: str,
    previous: dict,
    acceptance_issue: int,
) -> None:
    """Bind the assembled acceptance template to the finalized candidate identity."""
    record_path = root / TARGET_ACCEPTANCE_RELATIVE_PATH
    if not record_path.is_file():
        raise ValueError("V0251_TARGET_ACCEPTANCE_RECORD_MISSING")
    content = record_path.read_text(encoding="utf-8")
    for marker in TARGET_ACCEPTANCE_MATRIX_MARKERS:
        if marker not in content:
            raise ValueError("V0251_TARGET_ACCEPTANCE_MATRIX_MISSING {0}".format(marker))

    current_line = (
        "- 当前自动化候选：`{short_source}`，状态为 `candidate`；"
        "candidateBuildId：`{candidate_build_id}`；源码提交：`{source_commit}`；"
        "归档：`{archive_name}`；校验文件：`{checksum_name}`；"
        "目标验收：`manual-pending`（Issue #{acceptance_issue}）"
    ).format(
        short_source=source_commit[:7],
        candidate_build_id=candidate_build_id,
        source_commit=source_commit,
        archive_name=archive_name,
        checksum_name=checksum_name,
        acceptance_issue=acceptance_issue,
    )
    previous_line = (
        "- 上一被拒绝归档：`{archive_name}`，SHA-256：`{archive_sha256}`；"
        "candidateBuildId：`{candidate_build_id}`，状态为 `rejected`"
    ).format(
        archive_name=previous["archiveName"],
        archive_sha256=previous["archiveSha256"],
        candidate_build_id=previous["candidateBuildId"],
    )
    updated = []
    replaced_current = False
    replaced_previous = False
    for line in content.splitlines():
        if line.startswith("- 当前自动化候选："):
            updated.append(current_line)
            replaced_current = True
        elif line.startswith("- 上一被拒绝归档：") or line.startswith("- 被拒绝归档："):
            updated.append(previous_line)
            replaced_previous = True
        else:
            updated.append(line)
    if not replaced_current or not replaced_previous:
        raise ValueError("V0251_TARGET_ACCEPTANCE_IDENTITY_MARKER_MISSING")
    record_path.write_text("\n".join(updated) + "\n", encoding="utf-8")


def prepare(
    root: Path,
    date_tag: str,
    baseline_archive: Path,
    previous_candidate_archive: Path,
    source_commit: str,
    baseline_version: str = BASELINE_VERSION,
    acceptance_issue: int = 59,
) -> None:
    if baseline_version != BASELINE_VERSION:
        raise ValueError("V0250_BASELINE_VERSION_REQUIRED")
    if not date_tag or len(date_tag) != 8 or not date_tag.isdigit():
        raise ValueError("V0251_DATE_INVALID")
    try:
        datetime.strptime(date_tag, "%Y%m%d")
    except ValueError as exc:
        raise ValueError("V0251_DATE_INVALID") from exc
    if not SOURCE_COMMIT_RE.fullmatch(source_commit):
        raise ValueError("V0251_SOURCE_COMMIT_INVALID")
    baseline = baseline_metadata(baseline_archive, baseline_version)
    previous = previous_candidate_metadata(previous_candidate_archive)
    current_archive_name = candidate_archive_name(date_tag, source_commit)
    if previous["archiveName"] == current_archive_name:
        raise ValueError("V0251_PREVIOUS_CANDIDATE_BUILD_REUSE")
    rewrite_versions(root, ("0.23.1-alpha", "0.24.0-alpha", "0.25.0-alpha"))
    remove_previous_candidate_identity(root)

    manifest_path = root / "release-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["version"] = VERSION
    manifest["releaseDate"] = date_tag
    manifest["versionRule"] = "AI-WPS-P1-WORD-EXCEL-PPT-0.25.1-" + date_tag
    candidate_build_id = manifest["versionRule"] + "-" + source_commit
    manifest["deliveryPolicy"] = {
        "status": "candidate",
        "sourceAssembly": "explicit-allowlist",
        "allowlist": "release-allowlist.json",
        "fileHashes": "release-file-hashes.json",
        "auditScript": "scripts/audit_delivery.py",
        "candidateAuditScript": "scripts/audit_v0251_delivery.py",
        "lifecycleGate": "scripts/python38_delivery_lifecycle_gate.py",
        "targetAcceptanceRequired": True,
        "automatedGates": [
            "allowlist",
            "python38-compatibility",
            "plugin-contract",
            "format-rule-compile",
            "v0251-audit",
            "python38-lifecycle",
        ],
    }
    manifest["baseline"] = baseline
    manifest["formatReview"] = {
        "enabledByDefault": True,
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
    manifest["targetAcceptanceIssue"] = acceptance_issue
    manifest["targetAcceptance"] = {
        "status": "manual-pending",
        "required": True,
        "scope": "kylin-v10-wps-model-direct-and-read-only-format-review",
        "doesNotCloseIssue": True,
    }
    manifest["candidateEvidence"] = {
        "candidateBuildId": candidate_build_id,
        "sourceCommit": source_commit,
        "archiveChecksumFile": current_archive_name + ".sha256",
        "automatedResult": "candidate",
        "rollbackEntry": "installer/install_phase1.sh transaction log rollback",
        "acceptanceRecord": "Issue #{0}".format(acceptance_issue),
        "supersedes": previous,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    allowlist_path = root / "release-allowlist.json"
    allowlist = json.loads(allowlist_path.read_text(encoding="utf-8"))
    allowlist["version"] = VERSION
    allowlist_path.write_text(
        json.dumps(allowlist, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    prompt_path = root / manifest["adapter"]["systemPromptManifest"]
    prompt_manifest = json.loads(prompt_path.read_text(encoding="utf-8"))
    prompt_manifest["release"] = VERSION
    prompt_path.write_text(
        json.dumps(prompt_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    update_format_assets_manifest(root)
    record_candidate_lineage(
        root,
        previous,
        date_tag,
        source_commit,
        candidate_build_id,
        manifest["candidateEvidence"]["archiveChecksumFile"],
    )
    write_target_machine_acceptance_record(
        root,
        source_commit,
        candidate_build_id,
        current_archive_name,
        manifest["candidateEvidence"]["archiveChecksumFile"],
        previous,
        acceptance_issue,
    )
    write_candidate_delivery_note(
        root,
        date_tag,
        source_commit,
        candidate_build_id,
        current_archive_name,
        manifest["candidateEvidence"]["archiveChecksumFile"],
        acceptance_issue,
    )
    print("v0251_delivery_prepared=passed version={0}".format(VERSION))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--date", required=True)
    parser.add_argument("--baseline-archive", required=True, type=Path)
    parser.add_argument("--previous-candidate-archive", required=True, type=Path)
    parser.add_argument("--baseline-version", default=BASELINE_VERSION)
    parser.add_argument("--acceptance-issue", default=59, type=int)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args(argv)
    try:
        prepare(
            args.root.resolve(),
            args.date,
            args.baseline_archive.resolve(),
            args.previous_candidate_archive.resolve(),
            args.source_commit,
            args.baseline_version,
            args.acceptance_issue,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print("v0251_delivery_prepared=failed {0}".format(exc))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
