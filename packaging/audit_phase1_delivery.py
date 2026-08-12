#!/usr/bin/env python3
"""Audit a phase-one delivery tree against its exact allowlist and hashes."""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set


HASH_MANIFEST = "release-file-hashes.json"
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
}
FORBIDDEN_PARTS = {
    ".git",
    ".pytest_cache",
    "__pycache__",
    "tests",
    "node_modules",
    "logs",
    "provider_api_keys",
}
FORBIDDEN_NAMES = {
    ".DS_Store",
    "adapter.json",
    "provider_api_key",
    "standalone_adapter.py",
    "build_writing_policy_candidates.py",
}
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)https?://[^/\s:@]+:[^/\s@]+@"),
)
SECRET_ASSIGNMENT = re.compile(
    r"(?i)(?:api[_-]?key|apiKey|secret)\s*[:=]\s*[\"']([^\"']+)[\"']"
)
SENSITIVE_JSON_KEYS = {
    "apikey",
    "authorization",
    "password",
    "providerapikey",
    "secret",
    "token",
}
PLACEHOLDER_MARKERS = (
    "example",
    "placeholder",
    "replace",
    "your-",
    "workflow-editor",
    "none",
    "empty",
    "test-",
)


class AuditFailure(RuntimeError):
    pass


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
            raise AuditFailure(
                "DELIVERY_SYMLINK_REJECTED {0}".format(
                    path.relative_to(root).as_posix()
                )
            )
        if path.is_file():
            files.add(path.relative_to(root).as_posix())
    return files


def load_json(path: Path, error_code: str) -> Dict:
    if not path.is_file():
        raise AuditFailure("{0} {1}".format(error_code, path.name))
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AuditFailure("{0} {1}".format(error_code, path.name))
    return value


def safe_reference(root: Path, value: str, error_code: str) -> Path:
    path = Path(value)
    if (
        not value
        or "\\" in value
        or path.is_absolute()
        or ".." in path.parts
        or not path.parts
    ):
        raise AuditFailure("{0} {1}".format(error_code, value))
    return root / path


def audit_allowlist(
    root: Path,
    actual: Set[str],
    policy: Dict,
    allowed_missing: Optional[Set[str]] = None,
) -> None:
    if policy.get("schemaVersion") != 1:
        raise AuditFailure("RELEASE_ALLOWLIST_SCHEMA_INVALID")
    allowed = set(str(item) for item in policy.get("files", []))
    generated = set(str(item) for item in policy.get("generatedFiles", []))
    expected = allowed | generated
    unlisted = sorted(actual - expected)
    if unlisted:
        raise AuditFailure("FILE_NOT_ALLOWLISTED {0}".format(unlisted[0]))
    missing = sorted(
        (allowed | generated) - actual - (allowed_missing or set())
    )
    if missing:
        raise AuditFailure("ALLOWLISTED_FILE_MISSING {0}".format(missing[0]))

    for relative in sorted(actual):
        path = Path(relative)
        if any(part in FORBIDDEN_PARTS for part in path.parts):
            raise AuditFailure("FORBIDDEN_DELIVERY_PATH {0}".format(relative))
        if path.name in FORBIDDEN_NAMES or path.suffix == ".pyc":
            raise AuditFailure("FORBIDDEN_DELIVERY_FILE {0}".format(relative))
        if path.name.endswith((".tar.gz", ".zip")):
            raise AuditFailure("NESTED_ARCHIVE_REJECTED {0}".format(relative))
        if (
            path.name == "writing_policies.db"
            or path.name.startswith("writing_policies.db.backup-")
            or path.suffix == ".log"
            or ".draft." in path.name
        ):
            raise AuditFailure("RUNTIME_DATA_REJECTED {0}".format(relative))
        if path.suffix in {".csv", ".xlsx"} and not relative.startswith(
            "docs/import-templates/"
        ):
            raise AuditFailure("USER_IMPORT_CONTENT_REJECTED {0}".format(relative))


def audit_sensitive_values(root: Path, actual: Iterable[str]) -> None:
    for relative in sorted(actual):
        path = root / relative
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                raise AuditFailure("SENSITIVE_VALUE_DETECTED {0}".format(relative))
        for match in SECRET_ASSIGNMENT.finditer(text):
            value = match.group(1)
            lowered = value.lower()
            if any(
                marker in lowered for marker in PLACEHOLDER_MARKERS
            ):
                continue
            if len(value) >= 20 and any(char.isalpha() for char in value) and any(
                char.isdigit() for char in value
            ):
                raise AuditFailure("SENSITIVE_VALUE_DETECTED {0}".format(relative))
        if path.suffix.lower() == ".json":
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                continue

            def visit_json(value) -> None:
                if isinstance(value, dict):
                    for key, child in value.items():
                        normalized_key = re.sub(r"[^a-z0-9]", "", str(key).lower())
                        if normalized_key in SENSITIVE_JSON_KEYS and isinstance(child, str):
                            lowered = child.strip().lower()
                            if lowered and not any(
                                marker in lowered for marker in PLACEHOLDER_MARKERS
                            ):
                                raise AuditFailure(
                                    "SENSITIVE_VALUE_DETECTED {0}".format(relative)
                                )
                        visit_json(child)
                elif isinstance(value, list):
                    for child in value:
                        visit_json(child)

            visit_json(payload)


def audit_version(root: Path, manifest: Dict, allowlist: Dict) -> None:
    version = str(manifest.get("version", ""))
    adapter_version = str(manifest.get("adapter", {}).get("version", ""))
    if not version or adapter_version != version:
        raise AuditFailure("VERSION_MISMATCH release={0} adapter={1}".format(
            version, adapter_version
        ))
    if allowlist.get("version") != version:
        raise AuditFailure("ALLOWLIST_VERSION_MISMATCH")
    delivery_policy = manifest.get("deliveryPolicy", {})
    required_policy = {
        "status": "candidate",
        "sourceAssembly": "explicit-allowlist",
        "allowlist": "release-allowlist.json",
        "fileHashes": HASH_MANIFEST,
        "auditScript": "scripts/audit_delivery.py",
        "lifecycleGate": "scripts/python38_delivery_lifecycle_gate.py",
        "targetAcceptanceRequired": True,
    }
    if any(
        delivery_policy.get(key) != expected
        for key, expected in required_policy.items()
    ):
        raise AuditFailure("DELIVERY_POLICY_INVALID")

    for host in manifest.get("hosts", []):
        plugin = str(host.get("plugin", ""))
        plugin_root = safe_reference(
            root / "packages", plugin, "PLUGIN_PATH_REJECTED"
        )
        plugin_manifest = load_json(
            plugin_root / "manifest.json",
            "PLUGIN_MANIFEST_MISSING",
        )
        if plugin_manifest.get("version") != version:
            raise AuditFailure("PLUGIN_VERSION_MISMATCH {0}".format(plugin))


def referenced_manifest_paths(manifest: Dict) -> Set[str]:
    path_keys = {
        "hashManifest",
        "fileHashes",
        "lock",
        "notices",
        "operationsGuide",
        "promptTemplate",
        "pythonRuntimeGate",
        "lifecycleGate",
        "schema",
        "sources",
        "systemPromptManifest",
        "csvTemplate",
        "xlsxTemplate",
        "allowlist",
        "auditScript",
    }
    values: Set[str] = set()

    def visit(value) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key in path_keys and isinstance(child, str):
                    values.add(child)
                else:
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(manifest)
    return values


def audit_reference_closure(
    root: Path,
    manifest: Dict,
    allowed_missing: Optional[Set[str]] = None,
) -> None:
    for relative in sorted(referenced_manifest_paths(manifest)):
        target = safe_reference(root, relative, "REFERENCE_PATH_REJECTED")
        if not target.is_file() and relative not in (allowed_missing or set()):
            raise AuditFailure("REFERENCE_MISSING {0}".format(relative))

    for plugin_manifest_path in root.glob("packages/wps-ai-assistant*/manifest.json"):
        plugin = load_json(plugin_manifest_path, "PLUGIN_MANIFEST_INVALID")
        references = [plugin.get("entry")] + list(plugin.get("icons", {}).values())
        for reference in references:
            if not reference:
                continue
            target = safe_reference(
                plugin_manifest_path.parent,
                str(reference),
                "PLUGIN_REFERENCE_PATH_REJECTED",
            )
            if not target.is_file():
                raise AuditFailure(
                    "PLUGIN_REFERENCE_MISSING {0}:{1}".format(
                        plugin_manifest_path.parent.name, reference
                    )
                )

    for html_path in root.glob("packages/wps-ai-assistant*/*.html"):
        text = html_path.read_text(encoding="utf-8")
        for reference in re.findall(r'(?:src|href)=["\']([^"\']+)["\']', text):
            relative = reference.split("?", 1)[0]
            if relative.startswith(("http://", "https://", "#")):
                continue
            relative = relative.split("#", 1)[0]
            target = safe_reference(
                html_path.parent,
                relative,
                "HTML_REFERENCE_PATH_REJECTED",
            )
            if not target.is_file():
                raise AuditFailure(
                    "HTML_REFERENCE_MISSING {0}:{1}".format(
                        html_path.relative_to(root), relative
                    )
                )

    prompt_manifest_path = root / str(
        manifest.get("adapter", {}).get("systemPromptManifest", "")
    )
    if prompt_manifest_path.is_file():
        prompt_manifest = load_json(prompt_manifest_path, "PROMPT_MANIFEST_INVALID")
        tasks = prompt_manifest.get("tasks", {})
        stages = prompt_manifest.get("stages", {})
        if (
            not isinstance(tasks, dict)
            or not isinstance(stages, dict)
            or len(tasks) != manifest.get("adapter", {}).get("systemPromptCount")
            or prompt_manifest.get("release") != manifest.get("adapter", {}).get("version")
        ):
            raise AuditFailure("PROMPT_INVENTORY_MISMATCH")
        prompt_entries = list(tasks.items()) + list(stages.items())
        for task_name, item in sorted(prompt_entries):
            if not isinstance(item, dict):
                raise AuditFailure("PROMPT_ENTRY_INVALID {0}".format(task_name))
            prompt_path = safe_reference(
                prompt_manifest_path.parent,
                str(item.get("file", "")),
                "PROMPT_REFERENCE_PATH_REJECTED",
            )
            if not prompt_path.is_file():
                if (
                    task_name.startswith("word.document_review.full.")
                    and manifest.get("version") != "0.24.0-alpha"
                ):
                    continue
                raise AuditFailure("PROMPT_REFERENCE_MISSING {0}".format(prompt_path.name))
            expected = str(item.get("sha256", ""))
            if not re.fullmatch(r"[0-9a-f]{64}", expected) or sha256(prompt_path) != expected:
                raise AuditFailure("PROMPT_HASH_MISMATCH {0}".format(prompt_path.name))
            schema_reference = str(item.get("schema", "")).strip()
            schema_version = str(item.get("schemaVersion", "")).strip()
            schema_hash = str(item.get("schemaSha256", "")).strip().lower()
            if (
                task_name.startswith("word.document_review.full.")
                and manifest.get("version") == "0.24.0-alpha"
            ):
                if not schema_reference or not schema_version:
                    raise AuditFailure("PROMPT_SCHEMA_METADATA_MISSING {0}".format(task_name))
                schema_path = safe_reference(
                    prompt_manifest_path.parent,
                    schema_reference,
                    "PROMPT_SCHEMA_REFERENCE_REJECTED",
                )
                if not schema_path.is_file():
                    raise AuditFailure("PROMPT_SCHEMA_REFERENCE_MISSING {0}".format(schema_path.name))
                if not re.fullmatch(r"[0-9a-f]{64}", schema_hash) or sha256(schema_path) != schema_hash:
                    raise AuditFailure("PROMPT_SCHEMA_HASH_MISMATCH {0}".format(schema_path.name))
                schema_payload = load_json(schema_path, "PROMPT_SCHEMA_INVALID")
                if schema_payload.get("version") != schema_version:
                    raise AuditFailure("PROMPT_SCHEMA_VERSION_MISMATCH {0}".format(task_name))

    for runtime in (
        root / "packages/kylin-v10-arm-py38",
        root / "packages/kylin-v10-arm-py38-pip-bootstrap",
    ):
        hash_manifest = runtime / "SHA256SUMS"
        if not hash_manifest.is_file():
            continue
        referenced = set()
        for line in hash_manifest.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            digest, relative = line.split(None, 1)
            relative = relative.lstrip("*")
            target = safe_reference(
                runtime,
                relative,
                "RUNTIME_REFERENCE_PATH_REJECTED",
            )
            if not target.is_file():
                raise AuditFailure("RUNTIME_REFERENCE_MISSING {0}".format(relative))
            if sha256(target) != digest.lower():
                raise AuditFailure("RUNTIME_HASH_MISMATCH {0}".format(relative))
            referenced.add(relative)
        payload = {
            path.relative_to(runtime).as_posix()
            for path in runtime.rglob("*")
            if path.is_file()
            and path.name not in {"README.md", "SHA256SUMS"}
        }
        missing_hashes = sorted(payload - referenced)
        if missing_hashes:
            raise AuditFailure(
                "RUNTIME_HASH_REFERENCE_MISSING {0}".format(missing_hashes[0])
            )


def write_hashes(root: Path, actual: Set[str], version: str) -> None:
    files = {
        relative: sha256(root / relative)
        for relative in sorted(actual)
        if relative != HASH_MANIFEST
    }
    (root / HASH_MANIFEST).write_text(
        json.dumps(
            {"schemaVersion": 1, "version": version, "algorithm": "sha256", "files": files},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def verify_hashes(root: Path, actual: Set[str], version: str) -> None:
    hashes = load_json(root / HASH_MANIFEST, "FILE_HASH_MANIFEST_MISSING")
    if hashes.get("version") != version or hashes.get("algorithm") != "sha256":
        raise AuditFailure("FILE_HASH_MANIFEST_INVALID")
    expected = hashes.get("files", {})
    if set(expected) != actual - {HASH_MANIFEST}:
        raise AuditFailure("FILE_HASH_INVENTORY_MISMATCH")
    for relative, digest in sorted(expected.items()):
        if sha256(root / relative) != digest:
            raise AuditFailure("FILE_HASH_MISMATCH {0}".format(relative))


def audit(root: Path, write_hash_manifest: bool) -> None:
    if not root.is_dir():
        raise AuditFailure("DELIVERY_ROOT_MISSING")
    actual = delivery_files(root)
    allowlist = load_json(root / "release-allowlist.json", "RELEASE_ALLOWLIST_MISSING")
    manifest = load_json(root / "release-manifest.json", "RELEASE_MANIFEST_MISSING")
    audit_allowlist(
        root,
        actual,
        allowlist,
        {HASH_MANIFEST} if write_hash_manifest else set(),
    )
    audit_sensitive_values(root, actual)
    audit_version(root, manifest, allowlist)
    audit_reference_closure(
        root,
        manifest,
        {HASH_MANIFEST} if write_hash_manifest else set(),
    )
    version = str(manifest["version"])
    if write_hash_manifest:
        write_hashes(root, actual, version)
        actual = delivery_files(root)
        audit_allowlist(root, actual, allowlist)
    verify_hashes(root, actual, version)
    print(
        "delivery_audit=passed status=candidate files={0} version={1}".format(
            len(actual), version
        )
    )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("delivery_root", type=Path)
    parser.add_argument("--write-hashes", action="store_true")
    args = parser.parse_args(argv)
    try:
        audit(args.delivery_root.resolve(), args.write_hashes)
    except (AuditFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print("delivery_audit=failed {0}".format(exc))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
