"""Load and validate immutable AI-WPS format rule packs."""

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.config import BASE_DIR


RULE_PACK_SCHEMA_VERSION = 1
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DEFAULT_RULE_PACK_ROOT = BASE_DIR / "adapter_service/format_rule_packs"
LOCAL_VENDOR_ALGORITHM = BASE_DIR / "adapter_service/vendor/wx_doc_format_algorithm/algorithm.py"
LOCAL_SOURCE_MANIFEST = BASE_DIR / "adapter_service/vendor/wx_doc_format_algorithm/SOURCE_MANIFEST.json"


class FormatRulePackError(ValueError):
    pass


def _canonical_payload(pack: Dict[str, Any]) -> bytes:
    payload = copy.deepcopy(pack)
    payload.pop("integrity", None)
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _file_sha256(path: Path) -> str:
    return _sha256(path.read_bytes())


def validate_rule_pack(pack: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(pack, dict) or pack.get("schemaVersion") != RULE_PACK_SCHEMA_VERSION:
        raise FormatRulePackError("FORMAT_RULE_PACK_SCHEMA_INVALID")
    template = pack.get("template")
    algorithm = pack.get("algorithm")
    rules = pack.get("rules")
    if not isinstance(template, dict) or not isinstance(template.get("id"), str) or not template.get("id"):
        raise FormatRulePackError("FORMAT_RULE_PACK_TEMPLATE_INVALID")
    if not isinstance(pack.get("version"), str) or not pack["version"]:
        raise FormatRulePackError("FORMAT_RULE_PACK_VERSION_INVALID")
    if not isinstance(algorithm, dict) or not isinstance(algorithm.get("sourceVersion"), str):
        raise FormatRulePackError("FORMAT_RULE_PACK_ALGORITHM_INVALID")
    for key in ("adapterVersion", "sourceManifest", "sourceManifestSha256", "adapterPath", "adapterSha256"):
        if not isinstance(algorithm.get(key), str) or not algorithm[key]:
            raise FormatRulePackError("FORMAT_RULE_PACK_ALGORITHM_INVALID")
    if algorithm.get("writeBack") is not False:
        raise FormatRulePackError("FORMAT_RULE_PACK_WRITEBACK_ENABLED")
    if not SHA256_RE.fullmatch(algorithm["sourceManifestSha256"]) or not SHA256_RE.fullmatch(algorithm["adapterSha256"]):
        raise FormatRulePackError("FORMAT_RULE_PACK_ALGORITHM_HASH_INVALID")
    if not LOCAL_VENDOR_ALGORITHM.is_file() or _file_sha256(LOCAL_VENDOR_ALGORITHM) != algorithm["adapterSha256"]:
        raise FormatRulePackError("FORMAT_RULE_PACK_ALGORITHM_HASH_MISMATCH")
    if not LOCAL_SOURCE_MANIFEST.is_file() or _file_sha256(LOCAL_SOURCE_MANIFEST) != algorithm["sourceManifestSha256"]:
        raise FormatRulePackError("FORMAT_RULE_PACK_SOURCE_MANIFEST_MISMATCH")
    if not isinstance(rules, list) or not rules:
        raise FormatRulePackError("FORMAT_RULE_PACK_RULES_INVALID")
    source_hash = template.get("sourceDocumentSha256")
    if not isinstance(source_hash, str) or not SHA256_RE.fullmatch(source_hash):
        raise FormatRulePackError("FORMAT_RULE_PACK_SOURCE_HASH_INVALID")
    if "defaultTemplateValues" in algorithm or "defaultStyles" in algorithm:
        raise FormatRulePackError("FORMAT_RULE_PACK_UNAUTHORIZED_DEFAULTS")

    seen = set()
    for rule in rules:
        if not isinstance(rule, dict):
            raise FormatRulePackError("FORMAT_RULE_PACK_RULE_INVALID")
        for key in ("id", "algorithm", "source", "appliesTo", "unit", "tolerance", "severity", "enabled"):
            if key not in rule:
                raise FormatRulePackError("FORMAT_RULE_PACK_RULE_INVALID")
        if not all(isinstance(rule[key], str) and rule[key] for key in ("id", "algorithm", "source", "unit")):
            raise FormatRulePackError("FORMAT_RULE_PACK_RULE_INVALID")
        if not isinstance(rule["tolerance"], dict) or not isinstance(rule["enabled"], bool):
            raise FormatRulePackError("FORMAT_RULE_PACK_RULE_INVALID")
        if rule["id"] in seen:
            raise FormatRulePackError("FORMAT_RULE_PACK_RULE_DUPLICATE")
        seen.add(rule["id"])
        if not isinstance(rule["appliesTo"], list) or not rule["appliesTo"] or not all(isinstance(item, str) and item for item in rule["appliesTo"]):
            raise FormatRulePackError("FORMAT_RULE_PACK_RULE_SCOPE_INVALID")
        if rule["severity"] not in {"info", "warning", "error"}:
            raise FormatRulePackError("FORMAT_RULE_PACK_SEVERITY_INVALID")

    integrity = pack.get("integrity")
    if not isinstance(integrity, dict) or not SHA256_RE.fullmatch(str(integrity.get("contentSha256", ""))):
        raise FormatRulePackError("FORMAT_RULE_PACK_INTEGRITY_MISSING")
    if integrity["contentSha256"] != _sha256(_canonical_payload(pack)):
        raise FormatRulePackError("FORMAT_RULE_PACK_INTEGRITY_MISMATCH")
    return pack


class FormatRulePackLoader:
    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = Path(root) if root is not None else DEFAULT_RULE_PACK_ROOT

    def load(self, template_id: str) -> Dict[str, Any]:
        if not template_id or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", template_id):
            raise FormatRulePackError("FORMAT_RULE_PACK_TEMPLATE_ID_INVALID")
        candidates = sorted(self.root.glob(template_id + ".*.json"))
        candidates.extend(sorted(self.root.glob(template_id + ".json")))
        candidates.extend(
            path for path in sorted(self.root.glob("*.json")) if path not in candidates
        )
        for path in candidates:
            if path.is_symlink() or not path.is_file():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise FormatRulePackError("FORMAT_RULE_PACK_READ_FAILED") from exc
            validate_rule_pack(payload)
            if payload["template"]["id"] != template_id:
                continue
            return copy.deepcopy(payload)
        raise FileNotFoundError("Format rule pack not found: {0}".format(template_id))

    def list_metadata(self) -> List[Dict[str, Any]]:
        metadata = []
        for path in sorted(self.root.glob("*.json")):
            if path.is_symlink() or not path.is_file():
                continue
            payload = validate_rule_pack(json.loads(path.read_text(encoding="utf-8")))
            metadata.append(
                {
                    "templateId": payload["template"]["id"],
                    "version": payload["version"],
                    "contentSha256": payload["integrity"]["contentSha256"],
                }
            )
        return metadata
