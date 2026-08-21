#!/usr/bin/env python3
"""Audit the focused v0.25.0 authorized-format asset bundle."""

import argparse
import hashlib
import json
import sys
from pathlib import Path


EXPECTED_FILES = {
    "format-rule-assets-manifest.json",
    "adapter_service/app/core/models.py",
    "adapter_service/app/services/word/authorized_format_algorithm.py",
    "adapter_service/app/services/word/format_reviewer.py",
    "adapter_service/app/services/word/format_issue_support.py",
    "adapter_service/app/services/word/format_rule_pack.py",
    "adapter_service/tools/compile_format_rule_pack.py",
    "adapter_service/format_rule_packs/technical-document-template-rules.v1.0.0.json",
    "adapter_service/vendor/wx_doc_format_algorithm/__init__.py",
    "adapter_service/vendor/wx_doc_format_algorithm/algorithm.py",
    "adapter_service/vendor/wx_doc_format_algorithm/assets/wx_template.docx",
    "adapter_service/vendor/wx_doc_format_algorithm/SOURCE_MANIFEST.json",
    "adapter_service/vendor/wx_doc_format_algorithm/RULE_CLASSIFICATION.json",
    "adapter_service/vendor/wx_doc_format_algorithm/THIRD_PARTY_NOTICES.md",
    "packaging/check_python38_compatibility.py",
    "reference-workflows/format-semantics-text-v1.yml",
    "reference-workflows/format-semantics-vision-v1.yml",
}


def audit(root: Path) -> None:
    allowlist = json.loads((root / "release-allowlist.json").read_text(encoding="utf-8"))
    actual = set(allowlist.get("files", []))
    if actual != EXPECTED_FILES:
        raise ValueError("FORMAT_RULE_ASSET_ALLOWLIST_MISMATCH")
    if any("general-office" in path or "technical-file-format-requirements" in path for path in actual):
        raise ValueError("FORMAT_RULE_ASSET_HISTORICAL_REFERENCE")
    manifest = json.loads((root / "format-rule-assets-manifest.json").read_text(encoding="utf-8"))
    if manifest.get("version") != "0.25.0-format-rules-alpha":
        raise ValueError("FORMAT_RULE_ASSET_VERSION_INVALID")
    references = manifest.get("referenceWorkflows")
    if not isinstance(references, list) or len(references) != 2:
        raise ValueError("FORMAT_SEMANTIC_REFERENCE_WORKFLOWS_MISSING")
    expected_references = {
        "reference-workflows/format-semantics-text-v1.yml": "ffe15d87ff293b82c39b5865f9299f9c857a8662738ef8e9e6b4ec31f4bca1c3",
        "reference-workflows/format-semantics-vision-v1.yml": "ac2324e4620e4d945046745ac660393a9a51827796c902cc65ebc3ab49d52ec4",
    }
    seen_references = set()
    for reference in references:
        if not isinstance(reference, dict):
            raise ValueError("FORMAT_SEMANTIC_REFERENCE_WORKFLOW_INVALID")
        target = str(reference.get("target", ""))
        if target in seen_references:
            raise ValueError("FORMAT_SEMANTIC_REFERENCE_WORKFLOW_DUPLICATE")
        seen_references.add(target)
        if target not in expected_references or reference.get("sha256") != expected_references[target]:
            raise ValueError("FORMAT_SEMANTIC_REFERENCE_WORKFLOW_HASH_INVALID")
        if any(reference.get(key) is not False for key in ("autoImport", "autoUpdate", "autoOverwrite")):
            raise ValueError("FORMAT_SEMANTIC_REFERENCE_WORKFLOW_AUTO_MUTATION")
        content = (root / target).read_text(encoding="utf-8")
        if "contract_version: format_semantics.v1" not in content or "variable: result_json" not in content:
            raise ValueError("FORMAT_SEMANTIC_REFERENCE_WORKFLOW_CONTRACT_INVALID")
        if any(token in content.lower() for token in ("api_key", "apikey", "providerbaseurl", "servicebaseurl", "http://", "https://")):
            raise ValueError("FORMAT_SEMANTIC_REFERENCE_WORKFLOW_SECRET_OR_ADDRESS")
    if seen_references != set(expected_references):
        raise ValueError("FORMAT_SEMANTIC_REFERENCE_WORKFLOW_SET_INVALID")
    pack = json.loads(
        (root / "adapter_service/format_rule_packs/technical-document-template-rules.v1.0.0.json").read_text(
            encoding="utf-8"
        )
    )
    if pack.get("algorithm", {}).get("sourceVersion") != "0.12.15":
        raise ValueError("FORMAT_RULE_ASSET_SOURCE_VERSION_INVALID")
    if pack.get("rulePack", {}).get("id") != "technical-document-template-rules":
        raise ValueError("FORMAT_RULE_ASSET_ID_INVALID")
    if pack.get("rulePack", {}).get("displayName") != "技术文档模板规则":
        raise ValueError("FORMAT_RULE_ASSET_NAME_INVALID")
    if pack.get("rulePack", {}).get("version") != "1.0.0":
        raise ValueError("FORMAT_RULE_ASSET_RULE_VERSION_INVALID")
    if pack.get("rulePack", {}).get("sourceVersion") != "wx-doc-format 0.12.15":
        raise ValueError("FORMAT_RULE_ASSET_SOURCE_VERSION_LABEL_INVALID")
    if pack.get("algorithm", {}).get("writeBack") is not False:
        raise ValueError("FORMAT_RULE_ASSET_WRITEBACK_ENABLED")
    if not pack.get("algorithm", {}).get("adapterSha256"):
        raise ValueError("FORMAT_RULE_ASSET_ADAPTER_HASH_MISSING")
    algorithm_path = root / "adapter_service/vendor/wx_doc_format_algorithm/algorithm.py"
    actual_hash = hashlib.sha256(algorithm_path.read_bytes()).hexdigest()
    if actual_hash != pack["algorithm"]["adapterSha256"]:
        raise ValueError("FORMAT_RULE_ASSET_ADAPTER_HASH_MISMATCH")
    manifest_path = root / "adapter_service/vendor/wx_doc_format_algorithm/SOURCE_MANIFEST.json"
    manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    if manifest_hash != pack["algorithm"].get("sourceManifestSha256"):
        raise ValueError("FORMAT_RULE_ASSET_SOURCE_MANIFEST_HASH_MISMATCH")
    classification_path = root / "adapter_service/vendor/wx_doc_format_algorithm/RULE_CLASSIFICATION.json"
    classification_hash = hashlib.sha256(classification_path.read_bytes()).hexdigest()
    if classification_hash != pack["algorithm"].get("sourceClassificationSha256"):
        raise ValueError("FORMAT_RULE_ASSET_SOURCE_CLASSIFICATION_HASH_MISMATCH")
    template_path = root / "adapter_service/vendor/wx_doc_format_algorithm/assets/wx_template.docx"
    if hashlib.sha256(template_path.read_bytes()).hexdigest() != pack.get("template", {}).get("sourceDocumentSha256"):
        raise ValueError("FORMAT_RULE_ASSET_TEMPLATE_HASH_MISMATCH")
    if any(rule.get("classification") == "converter-only" for rule in pack.get("rules", [])):
        raise ValueError("FORMAT_RULE_ASSET_CONVERTER_RULE_ENABLED")
    if "defaultTemplateValues" in pack.get("algorithm", {}):
        raise ValueError("FORMAT_RULE_ASSET_DEFAULTS_PRESENT")
    print("format_rule_assets_audit=passed files={0}".format(len(actual)))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args(argv)
    try:
        audit(args.root.resolve())
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print("format_rule_assets_audit=failed {0}".format(exc))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
