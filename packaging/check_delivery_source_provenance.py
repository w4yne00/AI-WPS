#!/usr/bin/env python3
"""Require every delivery build input to match the recorded Git commit."""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set


class ProvenanceFailure(RuntimeError):
    pass


BUILD_INPUTS = (
    "packaging/format-rule-sources/technical-document-template-rules.v1.0.0.json",
    "packaging/format-rule-sources/technical-document-template-rules.v1.0.0.structure.json",
    "packaging/assemble_phase1_delivery.py",
    "packaging/audit_phase1_delivery.py",
    "packaging/audit_v0251_delivery.py",
    "packaging/build_v0251_delivery_kit.sh",
    "packaging/check_delivery_source_provenance.py",
    "packaging/check_python38_compatibility.py",
    "packaging/prepare_v0251_delivery.py",
    "packaging/build_v0260_preview1_delivery_kit.sh",
    "packaging/prepare_v0260_preview1_delivery.py",
    "packaging/audit_v0260_preview1_delivery.py",
    "packaging/python38_preview1_delivery_lifecycle_gate.py",
)


def _relative_path(repo_root: Path, path: Path) -> str:
    try:
        relative = path.resolve().relative_to(repo_root.resolve())
    except ValueError as exc:
        raise ProvenanceFailure("DELIVERY_SOURCE_PATH_OUTSIDE_REPOSITORY") from exc
    if not relative.parts or ".." in relative.parts:
        raise ProvenanceFailure("DELIVERY_SOURCE_PATH_INVALID")
    return relative.as_posix()


def _policy_sources(
    repo_root: Path,
    policy_path: Path,
    seen: Set[str],
) -> List[str]:
    policy_relative = _relative_path(repo_root, policy_path)
    if policy_relative in seen:
        raise ProvenanceFailure("DELIVERY_SOURCE_POLICY_CYCLE")
    seen.add(policy_relative)
    try:
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProvenanceFailure("DELIVERY_SOURCE_POLICY_INVALID") from exc
    if policy.get("schemaVersion") != 1:
        raise ProvenanceFailure("DELIVERY_SOURCE_POLICY_SCHEMA_INVALID")
    sources = [policy_relative]
    base_name = str(policy.get("basePolicy", "")).strip()
    if base_name:
        base_path = policy_path.parent / base_name
        sources.extend(_policy_sources(repo_root, base_path, seen))
    for entry in policy.get("entries", []):
        if not isinstance(entry, dict):
            raise ProvenanceFailure("DELIVERY_SOURCE_ENTRY_INVALID")
        entry_type = entry.get("type")
        source = Path(str(entry.get("source", "")))
        if source.is_absolute() or not source.parts or ".." in source.parts:
            raise ProvenanceFailure("DELIVERY_SOURCE_PATH_INVALID")
        if entry_type in {"file", "archive"}:
            sources.append(source.as_posix())
        elif entry_type == "tree":
            included = entry.get("include")
            if not isinstance(included, list) or not included:
                raise ProvenanceFailure("DELIVERY_SOURCE_TREE_INVALID")
            for value in included:
                relative = Path(str(value))
                if relative.is_absolute() or not relative.parts or ".." in relative.parts:
                    raise ProvenanceFailure("DELIVERY_SOURCE_PATH_INVALID")
                sources.append((source / relative).as_posix())
        else:
            raise ProvenanceFailure("DELIVERY_SOURCE_ENTRY_INVALID")
    return sources


def _git(repo_root: Path, arguments: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo_root)] + arguments,
        check=False,
        capture_output=True,
        text=True,
    )


def verify(repo_root: Path, source_allowlist: Path, source_commit: str) -> int:
    head = _git(repo_root, ["rev-parse", "HEAD"])
    if head.returncode != 0:
        raise ProvenanceFailure("DELIVERY_SOURCE_GIT_HEAD_UNAVAILABLE")
    complete_head = head.stdout.strip()
    if source_commit != complete_head:
        raise ProvenanceFailure(
            "DELIVERY_SOURCE_COMMIT_NOT_HEAD actual={0} expected={1}".format(
                source_commit, complete_head
            )
        )
    tracked_node_tests = _git(
        repo_root, ["ls-files", "--", "formal-plugin-kit/tests/*.test.js"]
    )
    if tracked_node_tests.returncode != 0:
        raise ProvenanceFailure("DELIVERY_SOURCE_NODE_TESTS_UNAVAILABLE")
    working_node_tests = {
        path.relative_to(repo_root).as_posix()
        for path in (repo_root / "formal-plugin-kit/tests").glob("*.test.js")
        if path.is_file()
    }
    sources = sorted(
        set(_policy_sources(repo_root, source_allowlist, set()))
        | set(BUILD_INPUTS)
        | set(tracked_node_tests.stdout.splitlines())
        | working_node_tests
    )
    for relative in sources:
        tracked = _git(repo_root, ["ls-files", "--error-unmatch", "--", relative])
        if tracked.returncode != 0:
            raise ProvenanceFailure(
                "DELIVERY_SOURCE_NOT_TRACKED {0}".format(relative)
            )
    status = _git(
        repo_root,
        ["status", "--porcelain=v1", "--untracked-files=all", "--"] + sources,
    )
    if status.returncode != 0:
        raise ProvenanceFailure("DELIVERY_SOURCE_STATUS_UNAVAILABLE")
    dirty = [line for line in status.stdout.splitlines() if line.strip()]
    if dirty:
        paths = ",".join(sorted(line[3:] for line in dirty)[:8])
        raise ProvenanceFailure("DELIVERY_SOURCE_DIRTY {0}".format(paths))
    return len(sources)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--source-allowlist", required=True, type=Path)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args(argv)
    try:
        count = verify(
            args.repo_root.resolve(),
            args.source_allowlist.resolve(),
            str(args.source_commit),
        )
    except ProvenanceFailure as exc:
        print("delivery_source_provenance=failed {0}".format(exc))
        return 1
    print(
        "delivery_source_provenance=passed source_commit={0} files={1}".format(
            args.source_commit, count
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
