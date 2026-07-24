import hashlib
import json
import re
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple

from .models import WritingPolicyError, normalize_key


PACK_SCHEMA_VERSION = 1
PACK_ID_RE = re.compile(r"^[a-z][a-z0-9.-]{2,63}$")
ENTRY_ID_RE = re.compile(r"^(term|rule)\.[a-z0-9][a-z0-9.-]{2,95}$")
SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
TASK_TYPES = ("smart_write", "smart_imitate", "document_review")
TASK_SCOPES = {
    "smart_write": "word.smart_write",
    "smart_imitate": "word.smart_imitation",
    "document_review": "word.document_review",
}
SCENE_IDS = ("yangqi", "cybersecurity", "official")
ENTRY_TYPES = ("term", "style", "anti_template")
MAX_PACK_ENTRIES = 1000

_PACK_FIELDS = {
    "schemaVersion",
    "packId",
    "version",
    "name",
    "sceneIds",
    "source",
    "review",
    "entries",
}
_SOURCE_FIELDS = {"name", "version", "commit", "license"}
_REVIEW_FIELDS = {"reviewedAt", "reviewedBy", "manifest"}
_COMMON_ENTRY_FIELDS = {
    "id",
    "type",
    "category",
    "priority",
    "defaultEnabled",
    "sourceRefs",
}
_TERM_FIELDS = _COMMON_ENTRY_FIELDS | {
    "preferredText",
    "aliases",
    "forbiddenVariants",
    "definition",
    "contextKeywords",
}
_RULE_FIELDS = _COMMON_ENTRY_FIELDS | {
    "name",
    "ruleText",
    "positiveExample",
    "negativeExample",
    "taskTypes",
    "sceneIds",
    "contextKeywords",
}


def default_pack_directory() -> Path:
    return Path(__file__).resolve().parents[3] / "writing_policy_packs"


def _invalid(message: str, code: str = "invalid_writing_policy_pack"):
    raise WritingPolicyError(code, message)


def _strict_fields(value: Mapping[str, object], fields: set, label: str) -> None:
    unknown = sorted(set(value) - fields)
    missing = sorted(fields - set(value))
    if unknown or missing:
        _invalid(
            "%s 字段不完整或包含未知字段：missing=%s unknown=%s"
            % (label, ",".join(missing), ",".join(unknown))
        )


def _text(value: object, label: str, maximum: int, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        _invalid("%s 必须为字符串。" % label)
    clean = value.strip()
    if not allow_empty and not clean:
        _invalid("%s 不能为空。" % label)
    if len(clean) > maximum:
        _invalid("%s 超出长度限制。" % label)
    return clean


def _string_list(
    value: object,
    label: str,
    *,
    allowed: Sequence[str] = (),
    maximum_items: int = 30,
    maximum_chars: int = 200,
    allow_empty: bool = False,
) -> Tuple[str, ...]:
    if not isinstance(value, list):
        _invalid("%s 必须为列表。" % label)
    if not allow_empty and not value:
        _invalid("%s 不能为空。" % label)
    if len(value) > maximum_items:
        _invalid("%s 条目过多。" % label)
    result = []
    seen = set()
    for item in value:
        clean = _text(item, label, maximum_chars)
        if allowed and clean not in allowed:
            _invalid("%s 包含无效值。" % label)
        key = normalize_key(clean)
        if key in seen:
            _invalid("%s 包含重复值。" % label)
        seen.add(key)
        result.append(clean)
    return tuple(result)


@dataclass(frozen=True)
class PackSource:
    name: str
    version: str
    commit: str
    license: str

    def public_dict(self) -> Dict[str, str]:
        public_commit = "" if self.commit == ("0" * 40) else self.commit
        return {
            "name": self.name,
            "version": self.version,
            "commit": public_commit,
            "license": self.license,
        }


@dataclass(frozen=True)
class WritingPolicyPack:
    pack_id: str
    version: str
    name: str
    scene_ids: Tuple[str, ...]
    source: PackSource
    reviewed_at: str
    reviewed_by: str
    review_manifest: str
    entries: Tuple[str, ...]

    def entry_dicts(self) -> Tuple[Dict[str, object], ...]:
        return tuple(json.loads(entry) for entry in self.entries)


@dataclass(frozen=True)
class WritingPolicyPackSnapshot:
    packs: Tuple[WritingPolicyPack, ...]

    def public_packs(self) -> List[Dict[str, object]]:
        return [
            {
                "packId": pack.pack_id,
                "name": pack.name,
                "version": pack.version,
                "sceneIds": list(pack.scene_ids),
                "entryCount": len(pack.entries),
                "source": pack.source.public_dict(),
            }
            for pack in self.packs
        ]

    def public_items(self, pack_id: str) -> List[Dict[str, object]]:
        for pack in self.packs:
            if pack.pack_id != pack_id:
                continue
            result = []
            for raw in pack.entry_dicts():
                item = deepcopy(raw)
                item["packId"] = pack.pack_id
                item["packName"] = pack.name
                item["packVersion"] = pack.version
                item["layer"] = "preset"
                item["source"] = pack.source.public_dict()
                result.append(item)
            return result
        raise WritingPolicyError(
            "writing_policy_pack_not_found",
            "未找到指定预置规范包。",
        )

    def matcher_items(
        self,
        pack_id: str,
        task_type: str,
        scene_id: str,
    ) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
        terms = []
        styles = []
        scope = TASK_SCOPES.get(task_type)
        if scope is None:
            _invalid("task_type 无效。")
        for item in self.public_items(pack_id):
            if not item.get("defaultEnabled", False):
                continue
            item_type = item["type"]
            if item_type == "term":
                terms.append(
                    {
                        "id": item["id"],
                        "type": "term",
                        "name": item["preferredText"],
                        "preferredText": item["preferredText"],
                        "aliases": list(item["aliases"]),
                        "forbiddenVariants": list(item["forbiddenVariants"]),
                        "definition": item["definition"],
                        "contextKeywords": list(item["contextKeywords"]),
                        "priority": _legacy_priority(item["priority"]),
                        "enabled": True,
                        "layer": "preset",
                        "packId": item["packId"],
                        "packVersion": item["packVersion"],
                    }
                )
                continue
            if task_type not in item["taskTypes"] or scene_id not in item["sceneIds"]:
                continue
            styles.append(
                {
                    "id": item["id"],
                    "type": item_type,
                    "category": item["category"],
                    "name": item["name"],
                    "ruleText": item["ruleText"],
                    "positiveExample": item["positiveExample"],
                    "negativeExample": item["negativeExample"],
                    "contextKeywords": list(item["contextKeywords"]),
                    "priority": _legacy_priority(item["priority"]),
                    "scope": scope,
                    "alwaysApply": True,
                    "enabled": True,
                    "layer": "preset",
                    "packId": item["packId"],
                    "packVersion": item["packVersion"],
                }
            )
        return terms, styles


def _legacy_priority(value: object) -> str:
    priority = int(value)
    if priority >= 67:
        return "high"
    if priority >= 34:
        return "medium"
    return "low"


def entry_content_sha256(entry: Mapping[str, object]) -> str:
    canonical = json.dumps(
        entry,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def validate_pack_data(data: object, file_name: str = "") -> WritingPolicyPack:
    if not isinstance(data, dict):
        _invalid("%s 不是 JSON 对象。" % file_name)
    if "review" not in data:
        _invalid("规范包缺少人工审阅信息。", "unreviewed_writing_policy_pack")
    _strict_fields(data, _PACK_FIELDS, "规范包")
    if data["schemaVersion"] != PACK_SCHEMA_VERSION:
        _invalid("规范包 schemaVersion 不受支持。")
    pack_id = _text(data["packId"], "packId", 64)
    if not PACK_ID_RE.fullmatch(pack_id):
        _invalid("packId 格式无效。")
    version = _text(data["version"], "version", 32)
    if not SEMVER_RE.fullmatch(version):
        _invalid("version 必须为语义版本。")
    name = _text(data["name"], "name", 80)
    scene_ids = _string_list(data["sceneIds"], "sceneIds", allowed=SCENE_IDS)

    source = data["source"]
    if not isinstance(source, dict):
        _invalid("source 必须为对象。")
    _strict_fields(source, _SOURCE_FIELDS, "source")
    source_model = PackSource(
        name=_text(source["name"], "source.name", 120),
        version=_text(source["version"], "source.version", 80),
        commit=_text(source["commit"], "source.commit", 40),
        license=_text(source["license"], "source.license", 80),
    )
    if not COMMIT_RE.fullmatch(source_model.commit):
        _invalid("source.commit 必须为完整提交哈希。")

    review = data["review"]
    if not isinstance(review, dict):
        _invalid("review 必须为对象。", "unreviewed_writing_policy_pack")
    _strict_fields(review, _REVIEW_FIELDS, "review")
    reviewed_at = _text(review["reviewedAt"], "review.reviewedAt", 10)
    if not DATE_RE.fullmatch(reviewed_at):
        _invalid("review.reviewedAt 格式无效。")
    reviewer = _text(review["reviewedBy"], "review.reviewedBy", 120)
    if normalize_key(reviewer) in {"ai", "agent", "codex", "automation"}:
        _invalid("预置规范必须由人工审阅。", "unreviewed_writing_policy_pack")
    manifest = _text(review["manifest"], "review.manifest", 160)
    if Path(manifest).name != manifest or not manifest.endswith(".review.json"):
        _invalid("review.manifest 必须为同目录审阅清单文件名。")

    entries = data["entries"]
    if not isinstance(entries, list) or not entries or len(entries) > MAX_PACK_ENTRIES:
        _invalid("entries 数量无效。")
    validated_entries = tuple(_validate_entry(entry, scene_ids) for entry in entries)
    return WritingPolicyPack(
        pack_id=pack_id,
        version=version,
        name=name,
        scene_ids=scene_ids,
        source=source_model,
        reviewed_at=reviewed_at,
        reviewed_by=reviewer,
        review_manifest=manifest,
        entries=tuple(
            json.dumps(entry, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            for entry in validated_entries
        ),
    )


def _validate_entry(entry: object, pack_scenes: Sequence[str]) -> Dict[str, object]:
    if not isinstance(entry, dict):
        _invalid("规范条目必须为对象。")
    item_type = entry.get("type")
    fields = _TERM_FIELDS if item_type == "term" else _RULE_FIELDS
    _strict_fields(entry, fields, "规范条目")
    item_id = _text(entry["id"], "entry.id", 100)
    if not ENTRY_ID_RE.fullmatch(item_id):
        _invalid("entry.id 格式无效。")
    if item_type not in ENTRY_TYPES:
        _invalid("entry.type 无效。")
    _text(entry["category"], "entry.category", 80)
    priority = entry["priority"]
    if isinstance(priority, bool) or not isinstance(priority, int) or not 0 <= priority <= 100:
        _invalid("entry.priority 必须为 0 至 100 的整数。")
    if not isinstance(entry["defaultEnabled"], bool):
        _invalid("entry.defaultEnabled 必须为布尔值。")
    _string_list(entry["sourceRefs"], "entry.sourceRefs", maximum_items=20, maximum_chars=300)

    if item_type == "term":
        _text(entry["preferredText"], "entry.preferredText", 200)
        _string_list(entry["aliases"], "entry.aliases", allow_empty=True)
        _string_list(
            entry["forbiddenVariants"],
            "entry.forbiddenVariants",
            allow_empty=True,
        )
        _text(entry["definition"], "entry.definition", 600)
        _string_list(
            entry["contextKeywords"],
            "entry.contextKeywords",
            allow_empty=True,
        )
    else:
        _text(entry["name"], "entry.name", 160)
        _text(entry["ruleText"], "entry.ruleText", 1000)
        _text(entry["positiveExample"], "entry.positiveExample", 600, allow_empty=True)
        _text(entry["negativeExample"], "entry.negativeExample", 600, allow_empty=True)
        _string_list(entry["taskTypes"], "entry.taskTypes", allowed=TASK_TYPES)
        scenes = _string_list(entry["sceneIds"], "entry.sceneIds", allowed=SCENE_IDS)
        if not set(scenes).issubset(set(pack_scenes)):
            _invalid("条目 sceneIds 必须属于规范包 sceneIds。")
        _string_list(
            entry["contextKeywords"],
            "entry.contextKeywords",
            allow_empty=True,
        )
    return deepcopy(entry)


def _load_review_manifest(
    root: Path, file_name: str, pack: WritingPolicyPack
) -> Dict[str, Tuple[str, str]]:
    path = root / file_name
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise WritingPolicyError(
            "unreviewed_writing_policy_pack",
            "无法读取规范包人工审阅清单。",
        ) from error
    fields = {"packId", "packVersion", "reviewedAt", "reviewedBy", "decisions"}
    if not isinstance(data, dict) or set(data) != fields:
        _invalid("人工审阅清单字段无效。", "unreviewed_writing_policy_pack")
    if data["packId"] != pack.pack_id or data["packVersion"] != pack.version:
        _invalid("人工审阅清单与规范包版本不匹配。", "unreviewed_writing_policy_pack")
    reviewed_at = _text(data["reviewedAt"], "review.reviewedAt", 10)
    reviewed_by = _text(data["reviewedBy"], "review.reviewedBy", 120)
    if (
        not DATE_RE.fullmatch(reviewed_at)
        or normalize_key(reviewed_by) in {"ai", "agent", "codex", "automation"}
        or reviewed_at != pack.reviewed_at
        or reviewed_by != pack.reviewed_by
    ):
        _invalid("人工审阅清单的审阅信息与规范包不匹配。", "unreviewed_writing_policy_pack")
    decisions = data["decisions"]
    if not isinstance(decisions, list):
        _invalid("人工审阅决定必须为列表。", "unreviewed_writing_policy_pack")
    result = {}
    for decision in decisions:
        if not isinstance(decision, dict) or set(decision) != {
            "id",
            "decision",
            "note",
            "contentSha256",
        }:
            _invalid("人工审阅决定字段无效。", "unreviewed_writing_policy_pack")
        item_id = _text(decision["id"], "review.id", 100)
        value = _text(decision["decision"], "review.decision", 20)
        digest = _text(decision["contentSha256"], "review.contentSha256", 64)
        if value not in ("approved", "rejected"):
            _invalid("人工审阅决定无效。", "unreviewed_writing_policy_pack")
        if not SHA256_RE.fullmatch(digest):
            _invalid("人工审阅内容摘要无效。", "unreviewed_writing_policy_pack")
        if item_id in result:
            _invalid("人工审阅清单包含重复 ID。", "unreviewed_writing_policy_pack")
        result[item_id] = (value, digest)
    entry_ids = {entry["id"] for entry in pack.entry_dicts()}
    if set(result) != entry_ids:
        _invalid("人工审阅清单必须覆盖规范包全部条目。", "unreviewed_writing_policy_pack")
    return result


def load_pack_snapshot(root: Path = None) -> WritingPolicyPackSnapshot:
    pack_root = Path(root or default_pack_directory())
    try:
        paths = sorted(
            path
            for path in pack_root.glob("*.json")
            if path.name != "schema-v1.json"
            and not path.name.endswith(".review.json")
            and path.name != "manifest.json"
        )
    except OSError as error:
        raise WritingPolicyError(
            "writing_policy_pack_unavailable",
            "无法读取预置规范包目录。",
        ) from error
    packs = []
    seen_pack_ids = set()
    seen_ids = {}
    seen_names = {}
    seen_content = {}
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise WritingPolicyError(
                "invalid_writing_policy_pack",
                "预置规范包无法读取或不是有效 JSON。",
            ) from error
        pack = validate_pack_data(data, path.name)
        if pack.pack_id in seen_pack_ids:
            raise WritingPolicyError(
                "duplicate_writing_policy_pack_id",
                "预置规范包包含重复稳定 ID。",
            )
        seen_pack_ids.add(pack.pack_id)
        decisions = _load_review_manifest(
            pack_root,
            str(data["review"]["manifest"]),
            pack,
        )
        for entry in pack.entry_dicts():
            item_id = entry["id"]
            if item_id in seen_ids:
                raise WritingPolicyError(
                    "duplicate_writing_policy_id",
                    "预置规范包包含重复稳定 ID。",
                )
            seen_ids[item_id] = pack.pack_id
            decision, approved_digest = decisions[item_id]
            if approved_digest != entry_content_sha256(entry):
                raise WritingPolicyError(
                    "unreviewed_writing_policy_pack",
                    "规范条目内容与人工审阅摘要不一致。",
                )
            if entry["defaultEnabled"] and decision != "approved":
                raise WritingPolicyError(
                    "unreviewed_writing_policy_pack",
                    "默认启用条目缺少人工通过决定。",
                )
            label = entry.get("preferredText") or entry.get("name")
            content = entry.get("definition") or entry.get("ruleText")
            name_key = (entry["type"], normalize_key(str(label)))
            content_key = (entry["type"], normalize_key(str(content)))
            if name_key in seen_names and seen_names[name_key] != normalize_key(str(content)):
                raise WritingPolicyError(
                    "conflicting_writing_policy_rule",
                    "预置规范包包含同名冲突条目。",
                )
            if content_key in seen_content:
                raise WritingPolicyError(
                    "duplicate_writing_policy_content",
                    "预置规范包包含重复内容。",
                )
            seen_names[name_key] = normalize_key(str(content))
            seen_content[content_key] = item_id
        packs.append(pack)
    return WritingPolicyPackSnapshot(tuple(packs))
