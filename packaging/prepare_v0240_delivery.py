#!/usr/bin/env python3
"""Finalize an assembled tree as a versioned v0.24.0 candidate package."""

import argparse
import json
from pathlib import Path
from typing import Iterable, List


TEXT_SUFFIXES = {".css", ".html", ".js", ".json", ".md", ".py", ".sh", ".txt", ".xml"}


def candidate_files(root: Path) -> Iterable[Path]:
    roots = [
        root / "release-manifest.json",
        root / "release-allowlist.json",
        root / "packages",
        root / "installer",
        root / "scripts",
        root / "wps-jsaddons",
    ]
    seen = set()
    for item in roots:
        paths = [item] if item.is_file() else item.rglob("*")
        for path in paths:
            if path in seen or not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            seen.add(path)
            yield path


def rewrite_versions(root: Path, old_version: str, new_version: str) -> List[str]:
    changed = []
    for path in candidate_files(root):
        text = path.read_text(encoding="utf-8")
        updated = text.replace(old_version, new_version)
        if updated != text:
            path.write_text(updated, encoding="utf-8")
            changed.append(path.relative_to(root).as_posix())
    return changed


def prepare(root: Path, version: str, date_tag: str) -> None:
    if version != "0.24.0-alpha":
        raise ValueError("V0240_VERSION_REQUIRED")
    manifest_path = root / "release-manifest.json"
    rewrite_versions(root, "0.23.1-alpha", version)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["version"] = version
    manifest["releaseDate"] = date_tag
    manifest["versionRule"] = "AI-WPS-P1-WORD-EXCEL-PPT-0.24.0-" + date_tag
    manifest.setdefault("baseline", {})["previousCandidate"] = "0.23.1-alpha"
    manifest.setdefault("deliveryPolicy", {})["status"] = "candidate"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    allowlist_path = root / "release-allowlist.json"
    allowlist = json.loads(allowlist_path.read_text(encoding="utf-8"))
    allowlist["version"] = version
    allowlist_path.write_text(
        json.dumps(allowlist, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    prompt_path = root / manifest["adapter"]["systemPromptManifest"]
    prompt_manifest = json.loads(prompt_path.read_text(encoding="utf-8"))
    prompt_manifest["release"] = version
    prompt_path.write_text(
        json.dumps(prompt_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print("v0240_delivery_prepared=passed version={0}".format(version))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--version", default="0.24.0-alpha")
    parser.add_argument("--date", required=True)
    args = parser.parse_args(argv)
    prepare(args.root.resolve(), args.version, args.date)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
