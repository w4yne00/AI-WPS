#!/usr/bin/env python3
"""Assemble the phase-one delivery tree from an explicit source allowlist."""

import argparse
import json
import shutil
import sys
import tarfile
from pathlib import Path
from typing import Dict, List, Optional


class AssemblyFailure(RuntimeError):
    pass


def normalized_relative(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise AssemblyFailure("ALLOWLIST_PATH_REJECTED {0}".format(value))
    return path


def explicit_relative(value: str) -> Path:
    if any(character in value for character in "*?[]"):
        raise AssemblyFailure("ALLOWLIST_GLOB_REJECTED {0}".format(value))
    return normalized_relative(value)


def repository_source(repo_root: Path, relative: Path) -> Path:
    current = repo_root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise AssemblyFailure("SOURCE_SYMLINK_REJECTED {0}".format(current))
    try:
        current.resolve().relative_to(repo_root.resolve())
    except ValueError:
        raise AssemblyFailure("SOURCE_PATH_OUTSIDE_REPOSITORY {0}".format(current))
    return current


def is_metadata_path(path: Path) -> bool:
    return any(part == ".DS_Store" or part.startswith("._") for part in path.parts)


def copy_file(source: Path, destination: Path, replace: bool = False) -> None:
    if source.is_symlink():
        raise AssemblyFailure("SOURCE_SYMLINK_REJECTED {0}".format(source))
    if not source.is_file():
        raise AssemblyFailure("SOURCE_FILE_MISSING {0}".format(source))
    if destination.exists() and not replace:
        raise AssemblyFailure("DELIVERY_PATH_COLLISION {0}".format(destination))
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(str(source), str(destination))
    shutil.copymode(str(source), str(destination))


def copy_tree(repo_root: Path, output: Path, entry: Dict) -> None:
    source_root = repository_source(
        repo_root, normalized_relative(str(entry["source"]))
    )
    target_root = output / normalized_relative(str(entry["target"]))
    included = [str(item) for item in entry.get("include", [])]
    if not source_root.is_dir() or not included:
        raise AssemblyFailure("ALLOWLIST_TREE_INVALID {0}".format(source_root))
    seen = set()
    for relative_value in included:
        relative_path = explicit_relative(relative_value)
        relative = relative_path.as_posix()
        if relative in seen:
            raise AssemblyFailure("ALLOWLIST_DUPLICATE_PATH {0}".format(relative))
        seen.add(relative)
        if is_metadata_path(relative_path):
            raise AssemblyFailure("ALLOWLIST_METADATA_REJECTED {0}".format(relative))
        source = repository_source(
            repo_root,
            source_root.relative_to(repo_root) / relative_path,
        )
        copy_file(
            source,
            target_root / relative_path,
            replace=bool(entry.get("replace", False)),
        )


def copy_archive(repo_root: Path, output: Path, entry: Dict) -> None:
    archive_path = repository_source(
        repo_root, normalized_relative(str(entry["source"]))
    )
    source_root = str(entry.get("sourceRoot", "")).strip("/")
    target_root = output / normalized_relative(str(entry["target"]))
    included = [str(item) for item in entry.get("include", [])]
    if not archive_path.is_file() or not source_root or not included:
        raise AssemblyFailure("ALLOWLIST_ARCHIVE_INVALID {0}".format(archive_path))
    requested = {}
    for relative_value in included:
        relative_path = explicit_relative(relative_value)
        relative = relative_path.as_posix()
        if relative in requested:
            raise AssemblyFailure("ALLOWLIST_DUPLICATE_PATH {0}".format(relative))
        if is_metadata_path(relative_path):
            raise AssemblyFailure("ALLOWLIST_METADATA_REJECTED {0}".format(relative))
        requested[relative] = relative_path
    found = set()
    with tarfile.open(str(archive_path), "r:gz") as archive:
        for member in archive.getmembers():
            if member.issym() or member.islnk():
                raise AssemblyFailure(
                    "SOURCE_ARCHIVE_LINK_REJECTED {0}".format(member.name)
                )
            member_path = Path(member.name)
            if member_path.is_absolute() or ".." in member_path.parts:
                raise AssemblyFailure(
                    "SOURCE_ARCHIVE_PATH_REJECTED {0}".format(member.name)
                )
            if not member.isfile():
                continue
            try:
                relative = member_path.relative_to(source_root).as_posix()
            except ValueError:
                continue
            if relative not in requested:
                continue
            if relative in found:
                raise AssemblyFailure("SOURCE_ARCHIVE_DUPLICATE {0}".format(relative))
            extracted = archive.extractfile(member)
            if extracted is None:
                raise AssemblyFailure(
                    "SOURCE_ARCHIVE_READ_FAILED {0}".format(member.name)
                )
            destination = target_root / requested[relative]
            if destination.exists() and not bool(entry.get("replace", False)):
                raise AssemblyFailure(
                    "DELIVERY_PATH_COLLISION {0}".format(destination)
                )
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(extracted.read())
            destination.chmod(member.mode & 0o777)
            found.add(relative)
    missing = sorted(set(requested) - found)
    if missing:
        raise AssemblyFailure("SOURCE_ARCHIVE_FILE_MISSING {0}".format(missing[0]))


def load_source_policy(source_allowlist: Path) -> Dict:
    policy = json.loads(source_allowlist.read_text(encoding="utf-8"))
    if policy.get("schemaVersion") != 1:
        raise AssemblyFailure("SOURCE_ALLOWLIST_SCHEMA_INVALID")
    base_name = str(policy.get("basePolicy", "")).strip()
    if not base_name:
        return policy
    base_path = (source_allowlist.parent / explicit_relative(base_name)).resolve()
    try:
        base_path.relative_to(source_allowlist.parent.resolve())
    except ValueError:
        raise AssemblyFailure("SOURCE_POLICY_OUTSIDE_PACKAGING {0}".format(base_name))
    if base_path == source_allowlist.resolve() or not base_path.is_file():
        raise AssemblyFailure("SOURCE_POLICY_BASE_MISSING {0}".format(base_name))
    base = load_source_policy(base_path)
    merged = dict(base)
    merged["version"] = policy.get("version", base.get("version"))
    merged["entries"] = list(base.get("entries", [])) + list(
        policy.get("entries", [])
    )
    merged["generatedFiles"] = sorted(
        set(base.get("generatedFiles", [])) | set(policy.get("generatedFiles", []))
    )
    return merged


def assemble(
    repo_root: Path,
    source_allowlist: Path,
    output: Path,
) -> None:
    if output.exists():
        raise AssemblyFailure("DELIVERY_OUTPUT_EXISTS {0}".format(output))
    source_policy = load_source_policy(source_allowlist)
    output.mkdir(parents=True)
    try:
        for entry in source_policy.get("entries", []):
            entry_type = entry.get("type")
            if entry_type == "file":
                copy_file(
                    repository_source(
                        repo_root,
                        normalized_relative(str(entry["source"])),
                    ),
                    output / normalized_relative(str(entry["target"])),
                    replace=bool(entry.get("replace", False)),
                )
            elif entry_type == "tree":
                copy_tree(repo_root, output, entry)
            elif entry_type == "archive":
                copy_archive(repo_root, output, entry)
            else:
                raise AssemblyFailure(
                    "SOURCE_ALLOWLIST_ENTRY_INVALID {0}".format(entry_type)
                )

        files = sorted(
            path.relative_to(output).as_posix()
            for path in output.rglob("*")
            if path.is_file()
        )
        release_allowlist = {
            "schemaVersion": 1,
            "version": source_policy.get("version"),
            "sourcePolicy": source_allowlist.name,
            "files": files,
            "generatedFiles": sorted(
                set(source_policy.get("generatedFiles", []))
                | {"release-allowlist.json"}
            ),
        }
        (output / "release-allowlist.json").write_text(
            json.dumps(release_allowlist, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except Exception:
        shutil.rmtree(str(output), ignore_errors=True)
        raise
    print("delivery_allowlist_assembly=passed files={0}".format(len(files)))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--source-allowlist", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        assemble(
            args.repo_root.resolve(),
            args.source_allowlist.resolve(),
            args.output.resolve(),
        )
    except (AssemblyFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print("delivery_allowlist_assembly=failed {0}".format(exc))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
