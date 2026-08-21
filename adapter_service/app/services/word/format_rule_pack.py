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
ACTIVE_RULE_PACK_ID = "technical-document-template-rules"
ACTIVE_RULE_PACK_NAME = "技术文档模板规则"
ACTIVE_RULE_PACK_VERSION = "1.0.0"
ACTIVE_RULE_PACK_SOURCE_VERSION = "wx-doc-format 0.12.15"
ACTIVE_RULE_PACK_FILENAME = "technical-document-template-rules.v1.0.0.json"
ALLOWED_CLASSIFICATIONS = {"normative-format", "normative-structure"}
DEFAULT_RULE_PACK_ROOT = BASE_DIR / "adapter_service/format_rule_packs"
LOCAL_VENDOR_ALGORITHM = BASE_DIR / "adapter_service/vendor/wx_doc_format_algorithm/algorithm.py"
LOCAL_SOURCE_MANIFEST = BASE_DIR / "adapter_service/vendor/wx_doc_format_algorithm/SOURCE_MANIFEST.json"
LOCAL_SOURCE_CLASSIFICATION = BASE_DIR / "adapter_service/vendor/wx_doc_format_algorithm/RULE_CLASSIFICATION.json"
LOCAL_SOURCE_TEMPLATE = BASE_DIR / "adapter_service/vendor/wx_doc_format_algorithm/assets/wx_template.docx"


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
    rule_pack = pack.get("rulePack")
    source_rules = pack.get("sourceRules")
    rules = pack.get("rules")
    if not isinstance(template, dict) or not isinstance(template.get("id"), str) or not template.get("id"):
        raise FormatRulePackError("FORMAT_RULE_PACK_TEMPLATE_INVALID")
    role_mappings = template.get("roleMappings", {})
    if not isinstance(role_mappings, dict):
        raise FormatRulePackError("FORMAT_RULE_PACK_ROLE_MAPPING_INVALID")

    def validate_mapping(value: Any) -> None:
        if isinstance(value, str):
            if not value:
                raise FormatRulePackError("FORMAT_RULE_PACK_ROLE_MAPPING_INVALID")
            return
        if isinstance(value, dict) and value and all(isinstance(key, str) and key for key in value):
            for nested in value.values():
                validate_mapping(nested)
            return
        raise FormatRulePackError("FORMAT_RULE_PACK_ROLE_MAPPING_INVALID")

    for mapping in role_mappings.values():
        validate_mapping(mapping)
    if not isinstance(pack.get("version"), str) or pack["version"] != ACTIVE_RULE_PACK_VERSION:
        raise FormatRulePackError("FORMAT_RULE_PACK_VERSION_INVALID")
    if not isinstance(rule_pack, dict):
        raise FormatRulePackError("FORMAT_RULE_PACK_METADATA_INVALID")
    if (
        rule_pack.get("id") != ACTIVE_RULE_PACK_ID
        or rule_pack.get("displayName") != ACTIVE_RULE_PACK_NAME
        or rule_pack.get("version") != ACTIVE_RULE_PACK_VERSION
        or rule_pack.get("sourceName") != "wx-doc-format"
        or rule_pack.get("sourceVersion") != ACTIVE_RULE_PACK_SOURCE_VERSION
        or rule_pack.get("active") is not True
    ):
        raise FormatRulePackError("FORMAT_RULE_PACK_METADATA_INVALID")
    if template.get("id") != ACTIVE_RULE_PACK_ID or template.get("name") != ACTIVE_RULE_PACK_NAME:
        raise FormatRulePackError("FORMAT_RULE_PACK_TEMPLATE_INVALID")
    if not isinstance(algorithm, dict) or not isinstance(algorithm.get("sourceVersion"), str):
        raise FormatRulePackError("FORMAT_RULE_PACK_ALGORITHM_INVALID")
    for key in (
        "adapterVersion", "sourceManifest", "sourceManifestSha256", "adapterPath", "adapterSha256",
        "sourceClassification", "sourceClassificationSha256",
    ):
        if not isinstance(algorithm.get(key), str) or not algorithm[key]:
            raise FormatRulePackError("FORMAT_RULE_PACK_ALGORITHM_INVALID")
    if algorithm.get("writeBack") is not False:
        raise FormatRulePackError("FORMAT_RULE_PACK_WRITEBACK_ENABLED")
    if not SHA256_RE.fullmatch(algorithm["sourceManifestSha256"]) or not SHA256_RE.fullmatch(algorithm["adapterSha256"]):
        raise FormatRulePackError("FORMAT_RULE_PACK_ALGORITHM_HASH_INVALID")
    if not SHA256_RE.fullmatch(algorithm["sourceClassificationSha256"]):
        raise FormatRulePackError("FORMAT_RULE_PACK_ALGORITHM_HASH_INVALID")
    if not LOCAL_VENDOR_ALGORITHM.is_file() or _file_sha256(LOCAL_VENDOR_ALGORITHM) != algorithm["adapterSha256"]:
        raise FormatRulePackError("FORMAT_RULE_PACK_ALGORITHM_HASH_MISMATCH")
    if not LOCAL_SOURCE_MANIFEST.is_file() or _file_sha256(LOCAL_SOURCE_MANIFEST) != algorithm["sourceManifestSha256"]:
        raise FormatRulePackError("FORMAT_RULE_PACK_SOURCE_MANIFEST_MISMATCH")
    if not LOCAL_SOURCE_CLASSIFICATION.is_file() or _file_sha256(LOCAL_SOURCE_CLASSIFICATION) != algorithm["sourceClassificationSha256"]:
        raise FormatRulePackError("FORMAT_RULE_PACK_SOURCE_CLASSIFICATION_MISMATCH")
    try:
        local_source_classification = json.loads(
            LOCAL_SOURCE_CLASSIFICATION.read_text(encoding="utf-8")
        )
    except (OSError, TypeError, ValueError):
        raise FormatRulePackError("FORMAT_RULE_PACK_SOURCE_CLASSIFICATION_MISMATCH")
    if not isinstance(local_source_classification, dict):
        raise FormatRulePackError("FORMAT_RULE_PACK_SOURCE_CLASSIFICATION_MISMATCH")
    if (
        local_source_classification.get("schemaVersion") != RULE_PACK_SCHEMA_VERSION
        or local_source_classification.get("sourceName") != rule_pack["sourceName"]
        or local_source_classification.get("sourceVersion") != algorithm["sourceVersion"]
    ):
        raise FormatRulePackError("FORMAT_RULE_PACK_SOURCE_CLASSIFICATION_MISMATCH")
    if not isinstance(rules, list) or not rules:
        raise FormatRulePackError("FORMAT_RULE_PACK_RULES_INVALID")
    source_hash = template.get("sourceDocumentSha256")
    if not isinstance(source_hash, str) or not SHA256_RE.fullmatch(source_hash):
        raise FormatRulePackError("FORMAT_RULE_PACK_SOURCE_HASH_INVALID")
    if not LOCAL_SOURCE_TEMPLATE.is_file() or _file_sha256(LOCAL_SOURCE_TEMPLATE) != source_hash:
        raise FormatRulePackError("FORMAT_RULE_PACK_TEMPLATE_SOURCE_MISMATCH")
    if "defaultTemplateValues" in algorithm or "defaultStyles" in algorithm:
        raise FormatRulePackError("FORMAT_RULE_PACK_UNAUTHORIZED_DEFAULTS")

    if not isinstance(source_rules, list) or not source_rules:
        raise FormatRulePackError("FORMAT_RULE_PACK_SOURCE_RULES_INVALID")
    source_rule_by_id = {}
    for source_rule in source_rules:
        if not isinstance(source_rule, dict):
            raise FormatRulePackError("FORMAT_RULE_PACK_SOURCE_RULE_INVALID")
        source_id = source_rule.get("id")
        if not isinstance(source_id, str) or not source_id or source_id in source_rule_by_id:
            raise FormatRulePackError("FORMAT_RULE_PACK_SOURCE_RULE_INVALID")
        if source_rule.get("category") not in ALLOWED_CLASSIFICATIONS | {"converter-only"}:
            raise FormatRulePackError("FORMAT_RULE_PACK_SOURCE_CATEGORY_INVALID")
        if not isinstance(source_rule.get("sourcePath"), str) or not source_rule["sourcePath"]:
            raise FormatRulePackError("FORMAT_RULE_PACK_SOURCE_RULE_INVALID")
        if not SHA256_RE.fullmatch(str(source_rule.get("sourceSha256", ""))):
            raise FormatRulePackError("FORMAT_RULE_PACK_SOURCE_HASH_INVALID")
        if not isinstance(source_rule.get("selected"), bool):
            raise FormatRulePackError("FORMAT_RULE_PACK_SOURCE_RULE_INVALID")
        source_rule_by_id[source_id] = source_rule
    if source_rules != local_source_classification.get("rules"):
        raise FormatRulePackError("FORMAT_RULE_PACK_SOURCE_CLASSIFICATION_MISMATCH")
    template_source_rule = source_rule_by_id.get("template.format_values")
    if not template_source_rule or template_source_rule.get("sourceSha256") != source_hash:
        raise FormatRulePackError("FORMAT_RULE_PACK_TEMPLATE_SOURCE_MISMATCH")

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
        if rule.get("classification") not in ALLOWED_CLASSIFICATIONS:
            raise FormatRulePackError("FORMAT_RULE_PACK_RULE_CLASSIFICATION_INVALID")
        source_rule = source_rule_by_id.get(rule["id"])
        if not source_rule or source_rule.get("category") != rule["classification"]:
            raise FormatRulePackError("FORMAT_RULE_PACK_RULE_SOURCE_MISMATCH")
        if source_rule.get("selected") is not True:
            raise FormatRulePackError("FORMAT_RULE_PACK_RULE_NOT_ALLOWLISTED")
        if rule.get("sourcePath") != source_rule.get("sourcePath") or rule.get("sourceSha256") != source_rule.get("sourceSha256"):
            raise FormatRulePackError("FORMAT_RULE_PACK_RULE_SOURCE_MISMATCH")

    integrity = pack.get("integrity")
    if not isinstance(integrity, dict) or not SHA256_RE.fullmatch(str(integrity.get("contentSha256", ""))):
        raise FormatRulePackError("FORMAT_RULE_PACK_INTEGRITY_MISSING")
    if integrity["contentSha256"] != _sha256(_canonical_payload(pack)):
        raise FormatRulePackError("FORMAT_RULE_PACK_INTEGRITY_MISMATCH")
    return pack


class FormatRulePackLoader:
    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = Path(root) if root is not None else DEFAULT_RULE_PACK_ROOT

    @property
    def active_path(self) -> Path:
        return self.root / ACTIVE_RULE_PACK_FILENAME

    def _assert_runtime_contents(self) -> None:
        unexpected = sorted(
            path.name
            for path in self.root.glob("*.json")
            if path.name != ACTIVE_RULE_PACK_FILENAME
        )
        if unexpected:
            raise FormatRulePackError("FORMAT_RULE_PACK_INACTIVE")

    def load(self, template_id: str) -> Dict[str, Any]:
        if not template_id or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", template_id):
            raise FormatRulePackError("FORMAT_RULE_PACK_TEMPLATE_ID_INVALID")
        if template_id != ACTIVE_RULE_PACK_ID:
            raise FormatRulePackError("FORMAT_RULE_PACK_INACTIVE")
        self._assert_runtime_contents()
        path = self.active_path
        if path.is_symlink() or not path.is_file():
            raise FileNotFoundError("Format rule pack not found: {0}".format(template_id))
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise FormatRulePackError("FORMAT_RULE_PACK_READ_FAILED") from exc
        validate_rule_pack(payload)
        if payload["template"]["id"] != template_id:
            raise FormatRulePackError("FORMAT_RULE_PACK_TEMPLATE_INVALID")
        return copy.deepcopy(payload)

    def list_metadata(self) -> List[Dict[str, Any]]:
        payload = self.load(ACTIVE_RULE_PACK_ID)
        return [
            {
                "templateId": payload["template"]["id"],
                "rulePackId": payload["rulePack"]["id"],
                "name": payload["rulePack"]["displayName"],
                "ruleVersion": payload["rulePack"]["version"],
                "sourceVersion": payload["rulePack"]["sourceVersion"],
                "active": payload["rulePack"]["active"],
                "version": payload["version"],
                "contentSha256": payload["integrity"]["contentSha256"],
                "sourceClassificationSha256": payload["algorithm"]["sourceClassificationSha256"],
            }
        ]
