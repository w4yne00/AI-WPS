import csv
import hmac
import io
import zipfile
from typing import Dict, Iterable, List, Sequence
from xml.sax.saxutils import escape

from .models import TASK_SCOPES, WRITING_POLICY_SCENES, WritingPolicyError, normalize_key


ROUNDTRIP_COLUMNS = (
    "操作",
    "稳定ID",
    "关联预置ID",
    "规范包ID",
    "规范包名称",
    "来源",
    "来源版本",
    "规范包版本",
    "层级",
    "覆盖状态",
    "类型",
    "适用范围",
    "名称",
    "标准写法/规则",
    "别名/禁用写法",
    "定义/说明",
    "推荐示例",
    "不推荐示例",
    "关键词",
    "任务范围",
    "场景范围",
    "优先级",
    "始终应用",
    "启用",
    "备注",
)
ROUNDTRIP_EXPORT_MARKER = "#AI-WPS-WRITING-POLICY-EXPORT:1"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)

_TYPE_LABELS = {
    "term": "术语",
    "style": "文体",
    "anti_template": "去模板化",
}
_SCOPE_LABELS = {
    "global": "全局",
    "word.smart_write": "智能编写",
    "word.smart_imitation": "智能仿写",
    "word.document_review": "文档审查",
}
_PRESET_TASK_SCOPES = {
    "smart_write": "word.smart_write",
    "smart_imitate": "word.smart_imitation",
    "document_review": "word.document_review",
}
_PRIORITY_LABELS = {
    "high": "高",
    "medium": "中",
    "low": "低",
}
_PRIORITY_VALUES = {value: key for key, value in _PRIORITY_LABELS.items()}
_TYPE_VALUES = {
    "术语": "term",
    "term": "term",
    "文体": "style",
    "风格": "style",
    "style": "style",
    "去模板化": "anti_template",
    "anti_template": "anti_template",
}
_BOOLEAN_VALUES = {"是": True, "否": False}
_OPERATION_VALUES = {
    "": "",
    "新增": "new",
    "修改": "modify",
    "覆盖": "modify",
    "停用": "disable",
    "恢复": "restore",
    "删除": "delete",
}
_EDITABLE_COLUMNS = (
    "类型",
    "适用范围",
    "名称",
    "标准写法/规则",
    "别名/禁用写法",
    "定义/说明",
    "推荐示例",
    "不推荐示例",
    "关键词",
    "任务范围",
    "场景范围",
    "优先级",
    "始终应用",
    "启用",
    "备注",
)


def export_roundtrip_csv(service, scope: str) -> bytes:
    rows = _export_rows(service, scope)
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow([ROUNDTRIP_EXPORT_MARKER])
    writer.writerow(ROUNDTRIP_COLUMNS)
    for row in rows:
        writer.writerow([_safe_spreadsheet_cell(row[column]) for column in ROUNDTRIP_COLUMNS])
    return b"\xef\xbb\xbf" + output.getvalue().encode("utf-8")


def export_roundtrip_xlsx(service, scope: str) -> bytes:
    rows = _export_rows(service, scope)
    values = [
        (ROUNDTRIP_EXPORT_MARKER,),
        ROUNDTRIP_COLUMNS,
    ]
    values.extend(
        tuple(_safe_spreadsheet_cell(row[column]) for column in ROUNDTRIP_COLUMNS)
        for row in rows
    )
    return _xlsx_bytes(values, "写作规范往返")


def build_roundtrip_preview(
    service,
    rows: Sequence[Dict[str, str]],
    file_meta: Dict[str, object],
    preview_store,
) -> Dict[str, object]:
    preset_items = {}
    for pack in service.list_packs():
        for item in service.list_preset_items(pack["packId"]):
            preset_items[str(item["id"])] = item
    organization_items = {}
    for item in service.store.list_items("global", "term"):
        organization_items[str(item["id"])] = item
    for item_type in ("style", "anti_template"):
        for item in service.store.list_items("organization", item_type):
            organization_items[str(item["id"])] = item
    planned_organization_items = dict(organization_items)

    operations = []
    changes = []
    conflicts = []
    errors = []
    seen_targets = set()
    stats = {
        "newCount": 0,
        "modifyCount": 0,
        "disableCount": 0,
        "restoreCount": 0,
        "deleteCount": 0,
        "unchangedCount": 0,
        "conflictCount": 0,
        "errorCount": 0,
    }
    for index, raw_row in enumerate(rows, start=3):
        row_number = int(getattr(raw_row, "_sourceRow", index))
        row = {str(key): str(value or "").strip() for key, value in raw_row.items()}
        try:
            operation = _operation_value(row.get("操作", ""))
            preset_id = row.get("关联预置ID", "")
            stable_id = row.get("稳定ID", "")
            target_key = ("preset", preset_id) if preset_id else ("organization", stable_id)
            if target_key[1]:
                if target_key in seen_targets:
                    raise _PreviewConflict("duplicate_target", "同一稳定 ID 在文件中重复。")
                seen_targets.add(target_key)

            if preset_id:
                baseline = preset_items.get(preset_id)
                if baseline is None:
                    raise _PreviewConflict(
                        "preset_not_found",
                        "关联的预置规范不存在或已不属于当前规范包快照。",
                    )
                _validate_preset_identity(row, baseline)
                current_operation = baseline.get("presetOperation")
                expected_operation = (
                    dict(current_operation) if current_operation is not None else None
                )
                if operation == "restore":
                    if current_operation is None:
                        raise _PreviewConflict(
                            "preset_already_restored",
                            "该预置规范当前没有组织覆盖或停用记录。",
                        )
                    internal = {
                        "action": "preset_restore",
                        "presetEntryId": preset_id,
                        "itemType": baseline["type"],
                        "expectedPresetOperation": expected_operation,
                    }
                    _append_change(
                        operations, changes, stats, row_number, "restore", internal, row
                    )
                    continue
                if operation == "disable":
                    internal = {
                        "action": "preset_disable",
                        "presetEntryId": preset_id,
                        "packId": baseline["packId"],
                        "itemType": baseline["type"],
                        "expectedPresetOperation": expected_operation,
                    }
                    _append_change(
                        operations, changes, stats, row_number, "disable", internal, row
                    )
                    continue
                if operation in ("new", "delete"):
                    raise _PreviewError(
                        "invalid_preset_operation",
                        "预置规范只允许修改、停用或恢复。",
                    )
                incoming_item = service.store.validate_item(_row_item(row))
                current_row = _preset_row(baseline)
                changed = any(
                    row.get(column, "") != current_row.get(column, "")
                    for column in _EDITABLE_COLUMNS
                )
                if operation == "modify" or changed:
                    internal = {
                        "action": "preset_override",
                        "presetEntryId": preset_id,
                        "packId": baseline["packId"],
                        "itemType": baseline["type"],
                        "item": incoming_item,
                        "expectedPresetOperation": expected_operation,
                    }
                    _append_change(
                        operations, changes, stats, row_number, "modify", internal, row
                    )
                else:
                    stats["unchangedCount"] += 1
                continue

            if stable_id:
                existing = organization_items.get(stable_id)
                if existing is None:
                    raise _PreviewConflict(
                        "organization_item_not_found",
                        "稳定 ID 对应的组织规范不存在。",
                    )
                if operation == "delete":
                    internal = {
                        "action": "delete",
                        "existingItemId": stable_id,
                        "itemType": existing["type"],
                        "expectedItem": dict(existing),
                    }
                    _append_change(
                        operations, changes, stats, row_number, "delete", internal, row
                    )
                    planned_organization_items.pop(stable_id, None)
                    continue
                if operation in ("disable", "restore", "new"):
                    raise _PreviewError(
                        "invalid_organization_operation",
                        "组织自定义规范只允许修改或显式删除。",
                    )
                if _TYPE_VALUES.get(row.get("类型", "")) != existing["type"]:
                    raise _PreviewConflict(
                        "organization_type_mismatch",
                        "规范类型与稳定 ID 对应的组织规范不一致。",
                    )
                incoming_item = service.store.validate_item(_row_item(row))
                _ensure_organization_conflict(
                    incoming_item,
                    planned_organization_items,
                    exclude_id=stable_id,
                )
                current_row = _organization_row(existing)
                changed = any(
                    row.get(column, "") != current_row.get(column, "")
                    for column in _EDITABLE_COLUMNS
                )
                if operation == "modify" or changed:
                    internal = {
                        "action": "update",
                        "existingItemId": stable_id,
                        "item": incoming_item,
                        "expectedItem": dict(existing),
                    }
                    _append_change(
                        operations, changes, stats, row_number, "modify", internal, row
                    )
                    planned_organization_items[stable_id] = dict(
                        incoming_item,
                        id=stable_id,
                    )
                else:
                    stats["unchangedCount"] += 1
                continue

            if operation not in ("", "new"):
                raise _PreviewError(
                    "missing_target_id",
                    "修改、停用、恢复或删除必须保留稳定 ID。",
                )
            incoming_item = service.store.validate_item(_row_item(row))
            _ensure_organization_conflict(
                incoming_item,
                planned_organization_items,
            )
            internal = {"action": "create", "item": incoming_item}
            _append_change(
                operations, changes, stats, row_number, "new", internal, row
            )
            planned_organization_items["row:%d" % row_number] = dict(
                incoming_item,
                id="row:%d" % row_number,
            )
        except _PreviewConflict as error:
            conflicts.append(
                _preview_problem(row_number, error.code, error.message, row)
            )
        except _PreviewError as error:
            errors.append(_preview_problem(row_number, error.code, error.message, row))
        except WritingPolicyError as error:
            errors.append(
                _preview_problem(row_number, error.code, error.message, row)
            )
    stats["conflictCount"] = len(conflicts)
    stats["errorCount"] = len(errors)
    token = preview_store.create(
        str(file_meta.get("fileName") or ""),
        operations,
        conflicts,
        errors=errors,
        stats=stats,
        file_meta=file_meta,
    )
    return dict(
        token,
        fileDigest=str(file_meta.get("sha256") or ""),
        changes=changes,
        conflicts=conflicts,
        errors=errors,
        **stats,
    )


def apply_roundtrip_preview(
    store,
    preview_token: str,
    file_digest: str,
    preview_store,
) -> Dict[str, object]:
    preview = preview_store.get(preview_token)
    expected_digest = str(
        dict(preview.get("fileMeta") or {}).get("sha256") or ""
    )
    supplied_digest = str(file_digest or "")
    if (
        len(expected_digest) != 64
        or len(supplied_digest) != 64
        or not hmac.compare_digest(expected_digest, supplied_digest)
    ):
        raise WritingPolicyError(
            "import_digest_mismatch",
            "导入文件摘要与预览不一致，请重新选择文件并预览。",
        )
    if int(dict(preview.get("stats") or {}).get("errorCount", 0)) > 0:
        raise WritingPolicyError(
            "import_preview_has_errors",
            "导入预览包含错误，修正文件后才能应用。",
        )
    preview = preview_store.consume(preview_token)
    stats = dict(preview.get("stats") or {})
    return store.apply_preview(
        list(preview.get("items") or []),
        dict(preview.get("fileMeta") or {}),
        stats={
            "conflictCount": int(stats.get("conflictCount", 0)),
            "errorCount": int(stats.get("errorCount", 0)),
        },
    )


class _PreviewError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class _PreviewConflict(_PreviewError):
    pass


def _append_change(
    operations,
    changes,
    stats,
    row_number: int,
    action: str,
    operation: Dict[str, object],
    row: Dict[str, str],
) -> None:
    operation = dict(operation, rowNumber=row_number)
    operations.append(operation)
    changes.append(
        {
            "rowNumber": row_number,
            "action": action,
            "stableId": row.get("稳定ID", ""),
            "presetEntryId": row.get("关联预置ID", ""),
            "name": row.get("标准写法/规则") or row.get("名称", ""),
        }
    )
    stats[action + "Count"] += 1


def _preview_problem(
    row_number: int,
    code: str,
    message: str,
    row: Dict[str, str],
) -> Dict[str, object]:
    return {
        "rowNumber": row_number,
        "row": row_number,
        "code": code,
        "message": "第 %d 行：%s" % (row_number, message),
        "stableId": row.get("稳定ID", ""),
        "presetEntryId": row.get("关联预置ID", ""),
    }


def _operation_value(value: str) -> str:
    operation = _OPERATION_VALUES.get(str(value or "").strip())
    if operation is None:
        raise _PreviewError(
            "invalid_roundtrip_operation",
            "操作必须为新增、修改、停用、恢复或删除。",
        )
    return operation


def _validate_preset_identity(
    row: Dict[str, str], baseline: Dict[str, object]
) -> None:
    if row.get("稳定ID") and row["稳定ID"] != str(baseline["id"]):
        raise _PreviewConflict("preset_id_mismatch", "稳定 ID 与关联预置 ID 不一致。")
    if row.get("规范包ID") and row["规范包ID"] != str(baseline["packId"]):
        raise _PreviewConflict("preset_pack_mismatch", "规范包 ID 与预置基线不一致。")
    incoming_type = _TYPE_VALUES.get(row.get("类型", ""))
    if incoming_type and incoming_type != baseline["type"]:
        raise _PreviewConflict("preset_type_mismatch", "规范类型与预置基线不一致。")


def _ensure_organization_conflict(
    incoming: Dict[str, object],
    existing_items: Dict[str, Dict[str, object]],
    exclude_id: str = "",
) -> None:
    if incoming["type"] == "term":
        incoming_tokens = _term_tokens(incoming)
        for item_id, existing in existing_items.items():
            if item_id == exclude_id or existing.get("type") != "term":
                continue
            if incoming_tokens.intersection(_term_tokens(existing)):
                raise _PreviewConflict(
                    "term_text_conflict",
                    "术语标准写法、别名或禁用写法与现有组织规范冲突。",
                )
        return
    incoming_key = (
        str(incoming.get("scope") or ""),
        normalize_key(str(incoming.get("name") or "")),
    )
    for item_id, existing in existing_items.items():
        if item_id == exclude_id or existing.get("type") == "term":
            continue
        existing_key = (
            str(existing.get("scope") or ""),
            normalize_key(str(existing.get("name") or "")),
        )
        if incoming_key == existing_key:
            raise _PreviewConflict(
                "style_name_conflict",
                "当前任务范围已存在同名组织规则。",
            )


def _term_tokens(item: Dict[str, object]) -> set:
    return {
        normalize_key(str(value))
        for value in (
            [item.get("preferredText", "")]
            + list(item.get("aliases") or ())
            + list(item.get("forbiddenVariants") or ())
        )
        if normalize_key(str(value))
    }


def _row_item(row: Dict[str, str]) -> Dict[str, object]:
    item_type = _TYPE_VALUES.get(row.get("类型", ""))
    if item_type is None:
        raise _PreviewError(
            "invalid_writing_policy_type",
            "规范类型必须为术语、文体或去模板化。",
        )
    priority = _PRIORITY_VALUES.get(row.get("优先级", ""))
    if priority is None:
        raise _PreviewError(
            "invalid_writing_policy_priority",
            "优先级必须为高、中或低。",
        )
    enabled = _boolean_value(row.get("启用", ""), "启用")
    if item_type == "term":
        aliases = []
        forbidden = []
        for value in _split_list(row.get("别名/禁用写法", "")):
            if value.startswith("别名:"):
                aliases.append(value[3:])
            elif value.startswith("禁用:"):
                forbidden.append(value[3:])
            elif value:
                aliases.append(value)
        return {
            "type": "term",
            "scope": "global",
            "category": row.get("名称", ""),
            "preferredText": row.get("标准写法/规则", ""),
            "aliases": aliases,
            "forbiddenVariants": forbidden,
            "definition": row.get("定义/说明", ""),
            "contextKeywords": _split_list(row.get("关键词", "")),
            "priority": priority,
            "enabled": enabled,
            "note": row.get("备注", ""),
        }
    task_types = _split_list(row.get("任务范围", ""))
    if not task_types:
        legacy_scope = next(
            (
                value
                for value, label in _SCOPE_LABELS.items()
                if label == row.get("适用范围", "")
            ),
            row.get("适用范围", ""),
        )
        task_types = list(TASK_SCOPES) if legacy_scope == "global" else [legacy_scope]
    if not task_types or any(value not in TASK_SCOPES for value in task_types):
        raise _PreviewError(
            "invalid_writing_policy_scope",
            "任务范围必须从三个 Word 任务中选择。",
        )
    scene_ids = _split_list(row.get("场景范围", ""))
    if not scene_ids or any(value not in WRITING_POLICY_SCENES for value in scene_ids):
        raise _PreviewError("invalid_writing_policy_scene", "场景范围无效。")
    return {
        "type": item_type,
        "scope": task_types[0] if len(task_types) == 1 else "global",
        "taskTypes": task_types,
        "sceneIds": scene_ids,
        "name": row.get("名称", ""),
        "ruleText": row.get("标准写法/规则", ""),
        "positiveExample": row.get("推荐示例", ""),
        "negativeExample": row.get("不推荐示例", ""),
        "contextKeywords": _split_list(row.get("关键词", "")),
        "alwaysApply": _boolean_value(row.get("始终应用", ""), "始终应用"),
        "priority": priority,
        "enabled": enabled,
        "note": row.get("备注", ""),
    }


def _boolean_value(value: str, label: str) -> bool:
    result = _BOOLEAN_VALUES.get(str(value or "").strip())
    if result is None:
        raise _PreviewError(
            "invalid_writing_policy_boolean",
            "%s 必须为是或否。" % label,
        )
    return result


def _split_list(value: str) -> List[str]:
    result = []
    buffer = []
    escaped = False
    for character in str(value or ""):
        if escaped:
            buffer.append(character)
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == "|":
            clean = "".join(buffer).strip()
            if clean:
                result.append(clean)
            buffer = []
        else:
            buffer.append(character)
    if escaped:
        buffer.append("\\")
    clean = "".join(buffer).strip()
    if clean:
        result.append(clean)
    return result


def _export_rows(service, scope: str) -> List[Dict[str, str]]:
    if scope not in ("effective", "organization"):
        raise WritingPolicyError(
            "invalid_export_scope",
            "导出范围必须为 effective 或 organization。",
        )
    rows = []
    for pack in service.list_packs():
        for item in service.list_preset_items(pack["packId"]):
            has_operation = item.get("presetOperation") is not None
            if scope == "organization" and not has_operation:
                continue
            if scope == "effective" and not item.get("effective", False):
                continue
            rows.append(_preset_row(item))

    organization_items = []
    organization_items.extend(service.store.list_items("global", "term"))
    organization_items.extend(service.store.list_items("organization", "style"))
    organization_items.extend(
        service.store.list_items("organization", "anti_template")
    )
    for item in organization_items:
        if scope == "effective" and not item.get("enabled", False):
            continue
        rows.append(_organization_row(item))
    return sorted(
        rows,
        key=lambda row: (
            row["层级"],
            row["规范包ID"],
            row["类型"],
            row["稳定ID"],
            row["名称"],
        ),
    )


def _preset_row(item: Dict[str, object]) -> Dict[str, str]:
    state = str(item.get("organizationState") or "preset")
    state_labels = {
        "preset": "预置基线",
        "overridden": "覆盖",
        "disabled": "停用",
    }
    source = dict(item.get("source") or {})
    return _item_row(
        item,
        stable_id=str(item.get("id") or ""),
        preset_id=str(item.get("id") or ""),
        pack_id=str(item.get("packId") or ""),
        pack_name=str(item.get("packName") or ""),
        source_name=str(source.get("name") or ""),
        source_version=str(source.get("version") or ""),
        pack_version=str(item.get("packVersion") or ""),
        layer="组织" if state != "preset" else "预置",
        organization_state=state_labels.get(state, state),
        enabled=bool(item.get("effective", False)),
    )


def _organization_row(item: Dict[str, object]) -> Dict[str, str]:
    return _item_row(
        item,
        stable_id=str(item.get("id") or ""),
        preset_id="",
        pack_id="",
        pack_name="",
        source_name="组织维护",
        source_version="",
        pack_version="",
        layer="组织",
        organization_state="组织自定义",
        enabled=bool(item.get("enabled", False)),
    )


def _item_row(
    item: Dict[str, object],
    *,
    stable_id: str,
    preset_id: str,
    pack_id: str,
    pack_name: str,
    source_name: str,
    source_version: str,
    pack_version: str,
    layer: str,
    organization_state: str,
    enabled: bool,
) -> Dict[str, str]:
    item_type = str(item.get("type") or "")
    task_types = _task_scopes(item)
    scene_ids = [str(value) for value in item.get("sceneIds") or ()]
    if item_type == "term":
        name = str(item.get("category") or "")
        content = str(item.get("preferredText") or "")
        variants = ["别名:" + str(value) for value in item.get("aliases") or ()]
        variants.extend(
            "禁用:" + str(value) for value in item.get("forbiddenVariants") or ()
        )
        definition = str(item.get("definition") or "")
        positive = ""
        negative = ""
        always_apply = False
        scope = "global"
    else:
        name = str(item.get("name") or "")
        content = str(item.get("ruleText") or "")
        variants = []
        definition = ""
        positive = str(item.get("positiveExample") or "")
        negative = str(item.get("negativeExample") or "")
        always_apply = bool(item.get("alwaysApply", True))
        scope = (
            task_types[0]
            if len(task_types) == 1
            else str(item.get("scope") or "global")
        )
    return {
        "操作": "",
        "稳定ID": stable_id,
        "关联预置ID": preset_id,
        "规范包ID": pack_id,
        "规范包名称": pack_name,
        "来源": source_name,
        "来源版本": source_version,
        "规范包版本": pack_version,
        "层级": layer,
        "覆盖状态": organization_state,
        "类型": _TYPE_LABELS.get(item_type, item_type),
        "适用范围": _SCOPE_LABELS.get(scope, scope),
        "名称": name,
        "标准写法/规则": content,
        "别名/禁用写法": _join_list(variants),
        "定义/说明": definition,
        "推荐示例": positive,
        "不推荐示例": negative,
        "关键词": _join_list(item.get("contextKeywords") or ()),
        "任务范围": _join_list(task_types),
        "场景范围": _join_list(scene_ids),
        "优先级": _PRIORITY_LABELS.get(
            str(item.get("priority") or "medium"),
            _numeric_priority_label(item.get("priority")),
        ),
        "始终应用": "是" if always_apply else "否",
        "启用": "是" if enabled else "否",
        "备注": str(item.get("note") or ""),
    }


def _task_scopes(item: Dict[str, object]) -> List[str]:
    item_type = str(item.get("type") or "")
    if item_type == "term":
        return list(TASK_SCOPES)
    values = []
    for raw in item.get("taskTypes") or ():
        value = _PRESET_TASK_SCOPES.get(str(raw), str(raw))
        if value in TASK_SCOPES and value not in values:
            values.append(value)
    if values:
        return values
    scope = str(item.get("scope") or "")
    return [scope] if scope in TASK_SCOPES else list(TASK_SCOPES)


def _numeric_priority_label(value: object) -> str:
    try:
        priority = int(value)
    except (TypeError, ValueError):
        return "中"
    if priority >= 67:
        return "高"
    if priority >= 34:
        return "中"
    return "低"


def _safe_spreadsheet_cell(value: object) -> str:
    text = "" if value is None else str(value)
    if text.startswith("'"):
        return "'" + text
    trimmed = text.lstrip()
    if trimmed and trimmed[0] in ("=", "+", "-", "@"):
        return "'" + text
    return text


def _join_list(values: Iterable[object]) -> str:
    escaped = []
    for value in values:
        text = str(value).replace("\\", "\\\\").replace("|", "\\|")
        escaped.append(text)
    return "|".join(escaped)


def _xlsx_bytes(rows: Sequence[Sequence[object]], sheet_name: str) -> bytes:
    sheet_rows = []
    for row_index, values in enumerate(rows, start=1):
        cells = []
        for column_index, value in enumerate(values, start=1):
            reference = "%s%d" % (_excel_column_name(column_index), row_index)
            cells.append(
                '<c r="%s" t="inlineStr"><is><t>%s</t></is></c>'
                % (reference, escape(str(value)))
            )
        sheet_rows.append('<row r="%d">%s</row>' % (row_index, "".join(cells)))
    parts = (
        (
            "[Content_Types].xml",
            b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            b'<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            b'<Default Extension="xml" ContentType="application/xml"/>'
            b'<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            b'<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            b"</Types>",
        ),
        (
            "_rels/.rels",
            b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            b'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            b"</Relationships>",
        ),
        (
            "xl/workbook.xml",
            (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                '<sheets><sheet name="%s" sheetId="1" r:id="rId1"/></sheets>'
                "</workbook>" % escape(sheet_name)
            ).encode("utf-8"),
        ),
        (
            "xl/_rels/workbook.xml.rels",
            b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            b'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            b"</Relationships>",
        ),
        (
            "xl/worksheets/sheet1.xml",
            (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                "<sheetData>%s</sheetData></worksheet>" % "".join(sheet_rows)
            ).encode("utf-8"),
        ),
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, content in parts:
            info = zipfile.ZipInfo(name, _FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 0
            info.external_attr = 0
            archive.writestr(info, content)
    return output.getvalue()


def _excel_column_name(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result
