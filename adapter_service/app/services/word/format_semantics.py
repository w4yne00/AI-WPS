"""Boundaries for model-assisted Word format semantics.

The deterministic formatter owns compliance decisions.  This module only
defines the small, auditable contract that a model may supplement.
"""

import hashlib
import json
import re
import time
from typing import Any, Callable, Dict, Optional, Tuple

from app.core.errors import AdapterError


FORMAT_SEMANTIC_OPERATIONS: Tuple[str, ...] = (
    "classify_role",
    "associate_caption",
    "suggest_figure_caption",
    "suggest_table_caption",
)
FORMAT_SEMANTIC_SCHEMA_VERSION = "format_semantics.v1"
MAX_FORMAT_SEMANTIC_INPUT_TOKENS = 8192
WORKFLOW_FORMAT_SEMANTIC_OUTPUT_TOKENS = 2048
MAX_FORMAT_SEMANTIC_OUTPUT_TOKENS = 4096
MAX_FORMAT_SEMANTIC_CALLS = 16
MAX_FORMAT_SEMANTIC_SUGGESTION_LENGTH = 80
FORMAT_MODEL_CAPABILITY_TABLE_VERSION = "2026-08-22"
FORMAT_MODEL_CAPABILITY_TABLE = {
    "deepseek-v4-flash": {
        "maxOutputTokens": 384000,
        "sourceDate": "2026-08-22",
        "sourceUrl": "https://api-docs.deepseek.com/quick_start/pricing",
    },
    "deepseek-v4-pro": {
        "maxOutputTokens": 384000,
        "sourceDate": "2026-08-22",
        "sourceUrl": "https://api-docs.deepseek.com/quick_start/pricing",
    },
    "glm-5.2": {
        "maxOutputTokens": 131072,
        "sourceDate": "2026-08-22",
        "sourceUrl": "https://docs.bigmodel.cn/cn/guide/start/concept-param",
    },
}
FORMAT_MODEL_CAPABILITY_TABLE_SHA256 = hashlib.sha256(
    json.dumps(
        FORMAT_MODEL_CAPABILITY_TABLE,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
).hexdigest()
_MARKDOWN_PREFIX = re.compile(r"(^|\s)([#>*`]|[-+]\s|\d+[.)]\s)")
_CAPTION_PREFIX = re.compile(r"^(?:图|表)\s*[0-9０-９一二三四五六七八九十]+(?:[：:.、\s]|$)")
_SAFE_FIELD_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,63}$")
_EVIDENCE_NUMBER = re.compile(r"(?<![\w])\d+(?:[.,]\d+)*(?:%|％)?")
_EVIDENCE_CJK_NUMBER = re.compile(
    r"[零〇一二三四五六七八九十百千万亿]+(?:年|月|日|季度|期|人|家|项|类|个|%)"
)
_PROTECTED_EVIDENCE_PATTERNS = (
    re.compile(r"(?:截至|上半年|下半年|同比|环比|\d{4}年|\d{1,2}季度|\d{1,2}月|\d{1,2}日)"),
    re.compile(r"(?:全国|全省|全市|国内|国外|中国|本省|本市|东部|中部|西部|省|市|区|县|地区|区域)"),
    re.compile(r"(?:公司|集团|机构|委员会|政府|大学|学院|研究院|中心|银行|医院|部门|局|所)"),
    re.compile(r"(?:平均|总计|占比|增速|增长率|均值|中位数|比例|人均|每[个家项]|总量|样本|基期|口径)"),
)


def _error(code: str, message: str, status_code: int = 409) -> AdapterError:
    return AdapterError(code, message, status_code=status_code)


def resolve_format_model_capability(model_name: str) -> Optional[Dict]:
    entry = FORMAT_MODEL_CAPABILITY_TABLE.get(str(model_name or "").strip())
    if not isinstance(entry, dict):
        return None
    return {
        "modelName": str(model_name).strip(),
        "maxOutputTokens": int(entry["maxOutputTokens"]),
        "sourceDate": str(entry["sourceDate"]),
        "sourceUrl": str(entry["sourceUrl"]),
        "tableVersion": FORMAT_MODEL_CAPABILITY_TABLE_VERSION,
        "tableSha256": FORMAT_MODEL_CAPABILITY_TABLE_SHA256,
    }


class FormatSemanticContract:
    """Validate the model-facing operation and response boundary."""

    @staticmethod
    def is_allowed_operation(operation: str) -> bool:
        return operation in FORMAT_SEMANTIC_OPERATIONS

    @staticmethod
    def estimate_input_tokens(value: Any) -> int:
        if not isinstance(value, str):
            value = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        # This deliberately overestimates mixed Chinese/Latin input and leaves
        # a fixed framing allowance for provider-specific prompt wrappers.
        return max(len(value), (len(value.encode("utf-8")) + 3) // 4) + 128

    @classmethod
    def require_input_budget(cls, value: Any) -> int:
        estimated = cls.estimate_input_tokens(value)
        if estimated > MAX_FORMAT_SEMANTIC_INPUT_TOKENS:
            raise _error(
                "FORMAT_SEMANTIC_INPUT_OVER_BUDGET",
                "格式语义单次输入超过 8,192 Token，未静默截断候选内容。",
                status_code=413,
            )
        return estimated

    @staticmethod
    def output_budget(task_auth: Dict) -> int:
        if str((task_auth or {}).get("accessMethod", "")) == "workflow_platform":
            return WORKFLOW_FORMAT_SEMANTIC_OUTPUT_TOKENS
        configured = (task_auth or {}).get("maxOutputTokens")
        if configured is None:
            capability = resolve_format_model_capability(
                str((task_auth or {}).get("modelName", ""))
            )
            configured = capability.get("maxOutputTokens") if capability else None
        if configured is None:
            return 0
        try:
            configured = int(configured)
        except (TypeError, ValueError):
            return 0
        return min(max(configured, 0), MAX_FORMAT_SEMANTIC_OUTPUT_TOKENS)

    @staticmethod
    def remaining_calls(used_calls: int) -> int:
        return max(MAX_FORMAT_SEMANTIC_CALLS - max(int(used_calls), 0), 0)

    @staticmethod
    def require_call_budget(used_calls: int) -> None:
        if int(used_calls) >= MAX_FORMAT_SEMANTIC_CALLS:
            raise _error(
                "FORMAT_SEMANTIC_CALL_LIMIT_EXCEEDED",
                "格式语义模型调用已达到每任务 16 次上限。",
            )

    @staticmethod
    def _allowed_item_keys(operation: str) -> set:
        if operation == "classify_role":
            return {"blockId", "role", "level", "headingLevel", "ordered", "numbered", "confidence", "attributes"}
        if operation == "associate_caption":
            return {"blockId", "targetBlockId", "status", "confidence"}
        return {"blockId", "suggestion", "status"}

    @staticmethod
    def _safe_field_list(fields: Any) -> str:
        safe = sorted(
            str(field)
            for field in fields
            if isinstance(field, str) and _SAFE_FIELD_NAME.fullmatch(field)
        )
        if not safe:
            return "无法显示的字段名"
        suffix = "等" if len(safe) > 5 else ""
        return "、".join(safe[:5]) + suffix

    @classmethod
    def response_json_schema(cls, operation: str) -> Dict:
        """Return the strict model-facing schema for one semantic operation."""
        if not cls.is_allowed_operation(operation):
            raise _error("FORMAT_SEMANTIC_OPERATION_NOT_ALLOWED", "格式语义操作不在白名单内。")
        binding_schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["contentSha256", "structureSha256", "formatSha256"],
            "properties": {
                "contentSha256": {"type": "string"},
                "structureSha256": {"type": "string"},
                "formatSha256": {"type": "string"},
            },
        }
        if operation == "classify_role":
            nullable_level = {
                "anyOf": [
                    {"type": "integer", "minimum": 1, "maximum": 9},
                    {"type": "null"},
                ]
            }
            nullable_boolean = {
                "anyOf": [{"type": "boolean"}, {"type": "null"}]
            }
            item_properties = {
                "blockId": {"type": "string", "minLength": 1, "maxLength": 128},
                "role": {
                    "type": "string",
                    "enum": [
                        "document_title", "heading", "body", "list_item", "note",
                        "caption", "toc_title", "toc_entry", "appendix_title",
                        "appendix_heading", "formula", "table_body", "unknown",
                    ],
                },
                "level": nullable_level,
                "headingLevel": nullable_level,
                "ordered": nullable_boolean,
                "numbered": nullable_boolean,
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "attributes": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["level", "ordered", "numbered"],
                    "properties": {
                        "level": nullable_level,
                        "ordered": nullable_boolean,
                        "numbered": nullable_boolean,
                    },
                },
            }
            required = list(item_properties.keys())
        elif operation == "associate_caption":
            item_properties = {
                "blockId": {"type": "string", "minLength": 1, "maxLength": 128},
                "targetBlockId": {"type": "string", "maxLength": 128},
                "status": {
                    "type": "string",
                    "enum": ["associated", "ambiguous", "unmatched"],
                },
                "confidence": {
                    "anyOf": [
                        {"type": "number", "minimum": 0, "maximum": 1},
                        {"type": "null"},
                    ]
                },
            }
            required = list(item_properties.keys())
        else:
            item_properties = {
                "blockId": {"type": "string", "minLength": 1, "maxLength": 128},
                "suggestion": {
                    "type": "string",
                    "maxLength": MAX_FORMAT_SEMANTIC_SUGGESTION_LENGTH,
                },
                "status": {
                    "anyOf": [
                        {
                            "type": "string",
                            "enum": [
                                "suggested", "text_evidence_only", "pixel_inspected",
                                "not_assessable",
                            ],
                        },
                        {"type": "null"},
                    ],
                },
            }
            required = list(item_properties.keys())
        return {
            "type": "object",
            "additionalProperties": False,
            "required": ["schemaVersion", "operation", "snapshotBinding", "items"],
            "properties": {
                "schemaVersion": {"type": "string", "const": FORMAT_SEMANTIC_SCHEMA_VERSION},
                "operation": {"type": "string", "const": operation},
                "snapshotBinding": binding_schema,
                "items": {
                    "type": "array",
                    "maxItems": 512,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": required,
                        "properties": item_properties,
                    },
                },
            },
        }

    @staticmethod
    def _as_bounded_confidence(value: Any) -> float:
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            raise _error("FORMAT_SEMANTIC_RESPONSE_INVALID", "模型置信度无效。")
        if not 0 <= confidence <= 1:
            raise _error("FORMAT_SEMANTIC_RESPONSE_INVALID", "模型置信度超出范围。")
        return confidence

    @staticmethod
    def _evidence_text(candidate: Dict) -> str:
        evidence = candidate.get("evidence", {}) if isinstance(candidate, dict) else {}
        if not isinstance(evidence, dict):
            return ""

        values = []

        def collect(value: Any) -> None:
            if isinstance(value, str):
                values.append(value)
            elif isinstance(value, dict):
                for nested in value.values():
                    collect(nested)
            elif isinstance(value, list):
                for nested in value:
                    collect(nested)

        collect(evidence)
        return " ".join(values)

    @staticmethod
    def _evidence_contains(needle: str, haystack: str) -> bool:
        normalize = lambda value: re.sub(r"[\s，。；：、,.!?！？（）()\[\]{}]", "", str(value))
        return normalize(needle) in normalize(haystack)

    @classmethod
    def validate_evidence_bound_suggestion(cls, suggestion: str, candidate: Dict) -> None:
        evidence_status = str((candidate.get("evidence") or {}).get("evidenceStatus", ""))
        if evidence_status not in {"complete", "restricted"}:
            raise _error(
                "FORMAT_SEMANTIC_EVIDENCE_INSUFFICIENT",
                "表题证据不足，无法可靠生成建议。",
            )
        evidence_text = cls._evidence_text(candidate)
        for token in _EVIDENCE_NUMBER.findall(suggestion) + _EVIDENCE_CJK_NUMBER.findall(suggestion):
            if not cls._evidence_contains(token, evidence_text):
                raise _error(
                    "FORMAT_SEMANTIC_EVIDENCE_VIOLATION",
                    "表题建议引入了证据外的数值或时间事实。",
                )
        for pattern in _PROTECTED_EVIDENCE_PATTERNS:
            for match in pattern.finditer(suggestion):
                if not cls._evidence_contains(match.group(0), evidence_text):
                    raise _error(
                        "FORMAT_SEMANTIC_EVIDENCE_VIOLATION",
                    "表题建议引入了证据外的机构、时间、地域或统计口径。",
                )

    @classmethod
    def validate_figure_caption_suggestion(
        cls, suggestion: str, candidate: Dict, allow_pixel_inspection: bool
    ) -> str:
        evidence = candidate.get("evidence") if isinstance(candidate, dict) else {}
        evidence = evidence if isinstance(evidence, dict) else {}
        pixel_verified = candidate.get("pixelEvidenceVerified") is True
        evidence_status = str(evidence.get("evidenceStatus") or "")
        # Older model-configuration probes used synthetic figure candidates
        # without an evidence view. Keep that probe contract compatible; real
        # review candidates always carry evidence and therefore take the
        # stricter branch below.
        if "evidence" not in candidate:
            return "text_evidence_only"
        if pixel_verified:
            if not allow_pixel_inspection:
                raise _error(
                    "IMAGE_SEMANTICS_DISABLED",
                    "图片语义总开关关闭时不能标记为已完成视觉判断。",
                )
            return "pixel_inspected"
        if evidence_status not in {"complete", "restricted"}:
            raise _error(
                "FORMAT_SEMANTIC_EVIDENCE_INSUFFICIENT",
                "图题证据不足，无法可靠生成建议。",
            )
        cls.validate_evidence_bound_suggestion(suggestion, candidate)
        return "text_evidence_only"

    @classmethod
    def _normalize_role_item(cls, item: Dict, candidate: Dict) -> Dict:
        role = str(item.get("role", "")).strip()
        attributes = item.get("attributes", {})
        if not isinstance(attributes, dict) or set(attributes) - {"level", "ordered", "numbered"}:
            raise _error("FORMAT_SEMANTIC_RESPONSE_INVALID", "模型角色属性字段无效。")
        attributes = dict(attributes)
        if role.startswith("heading") and role[7:].isdigit():
            attributes["level"] = int(role[7:])
            role = "heading"
        elif role.startswith("list") and "_" in role:
            prefix, kind = role.split("_", 1)
            if prefix[4:].isdigit() and kind in {"numbered", "plain"}:
                attributes.update({"level": int(prefix[4:]), "ordered": kind == "numbered"})
                role = "list_item"
        elif role == "numbered_note":
            attributes["numbered"] = True
            role = "note"

        if any(key in item for key in ("level", "headingLevel")):
            level = item.get("level", item.get("headingLevel"))
            if isinstance(level, bool) or not isinstance(level, int) or not 1 <= level <= 9:
                raise _error("FORMAT_SEMANTIC_RESPONSE_INVALID", "模型角色层级无效。")
            attributes["level"] = level
        if "level" in attributes:
            level = attributes["level"]
            if isinstance(level, bool) or not isinstance(level, int) or not 1 <= level <= 9:
                raise _error("FORMAT_SEMANTIC_RESPONSE_INVALID", "模型角色层级无效。")
        for key in ("ordered", "numbered"):
            if key in item:
                if not isinstance(item[key], bool):
                    raise _error("FORMAT_SEMANTIC_RESPONSE_INVALID", "模型角色属性类型无效。")
                attributes[key] = item[key]
            if key in attributes and not isinstance(attributes[key], bool):
                raise _error("FORMAT_SEMANTIC_RESPONSE_INVALID", "模型角色属性类型无效。")

        allowed = candidate.get("allowedTargets", [])
        if not any(
            isinstance(target, dict)
            and target.get("role") == role
            and all(attributes.get(key) == value for key, value in (target.get("attributes") or {}).items())
            for target in allowed
        ):
            raise _error("FORMAT_SEMANTIC_RESPONSE_INVALID", "模型角色超出候选允许范围。")
        normalized = {
            "blockId": str(item["blockId"]).strip(),
            "role": role,
            "confidence": cls._as_bounded_confidence(item.get("confidence")),
        }
        if attributes:
            normalized["attributes"] = attributes
        return normalized

    @classmethod
    def validate_response(
        cls,
        operation: str,
        payload: Dict,
        candidates: Dict[str, Dict],
        snapshot_binding: Dict[str, str],
        require_complete: bool = False,
        allow_pixel_inspection: bool = False,
    ) -> Dict:
        if not cls.is_allowed_operation(operation):
            raise _error("FORMAT_SEMANTIC_OPERATION_NOT_ALLOWED", "格式语义操作不在白名单内。")
        if not isinstance(payload, dict):
            raise _error("FORMAT_SEMANTIC_RESPONSE_INVALID", "格式语义响应必须是 JSON 对象。")
        allowed_payload_keys = {"schemaVersion", "operation", "snapshotBinding", "items"}
        unexpected_payload_keys = set(payload) - allowed_payload_keys
        if unexpected_payload_keys:
            raise _error(
                "FORMAT_SEMANTIC_RESPONSE_INVALID",
                "模型返回了协议未定义的顶层字段：{0}。".format(
                    cls._safe_field_list(unexpected_payload_keys)
                ),
            )
        if payload.get("schemaVersion") != FORMAT_SEMANTIC_SCHEMA_VERSION:
            raise _error("FORMAT_SEMANTIC_RESPONSE_INVALID", "格式语义响应版本不受支持。")
        if payload.get("operation") != operation:
            raise _error("FORMAT_SEMANTIC_RESPONSE_INVALID", "格式语义响应操作与请求不一致。")
        returned_binding = payload.get("snapshotBinding")
        if returned_binding != snapshot_binding:
            raise _error("FORMAT_SEMANTIC_BINDING_INVALID", "格式语义响应未绑定当前格式快照。")
        items = payload.get("items")
        if not isinstance(items, list) or len(items) > len(candidates):
            raise _error("FORMAT_SEMANTIC_RESPONSE_INVALID", "格式语义响应条目数量无效。")
        normalized = []
        seen = set()
        for item_index, item in enumerate(items):
            if not isinstance(item, dict):
                raise _error("FORMAT_SEMANTIC_RESPONSE_INVALID", "格式语义响应条目格式无效。")
            item = dict(item)
            for optional_key in (
                "level", "headingLevel", "ordered", "numbered", "confidence", "status"
            ):
                if item.get(optional_key) is None:
                    item.pop(optional_key, None)
            if isinstance(item.get("attributes"), dict):
                item["attributes"] = {
                    key: value
                    for key, value in item["attributes"].items()
                    if value is not None
                }
            allowed_item_keys = cls._allowed_item_keys(operation)
            unexpected_item_keys = set(item) - allowed_item_keys
            if unexpected_item_keys:
                raise _error(
                    "FORMAT_SEMANTIC_RESPONSE_INVALID",
                    "模型返回了协议未定义的字段：{0}。".format(
                        "、".join(
                            "items[{0}].{1}".format(item_index, name)
                            for name in cls._safe_field_list(unexpected_item_keys).split("、")
                        )
                    ),
                )
            block_id = str(item.get("blockId", "")).strip()
            if not block_id or block_id in seen or block_id not in candidates:
                raise _error("FORMAT_SEMANTIC_CANDIDATE_OUT_OF_RANGE", "格式语义响应引用了未请求的候选。")
            seen.add(block_id)
            candidate = candidates[block_id]
            if operation == "classify_role":
                clean = cls._normalize_role_item(item, candidate)
            elif operation == "associate_caption":
                target_id = str(item.get("targetBlockId", "")).strip()
                allowed_targets = set(candidate.get("allowedTargetBlockIds", []))
                status = item.get("status")
                if status not in {"associated", "ambiguous", "unmatched"}:
                    raise _error("FORMAT_SEMANTIC_RESPONSE_INVALID", "题注关联状态无效。")
                if target_id and target_id not in allowed_targets:
                    raise _error("FORMAT_SEMANTIC_CANDIDATE_OUT_OF_RANGE", "题注关联目标不在候选范围内。")
                if status == "associated" and not target_id:
                    raise _error("FORMAT_SEMANTIC_RESPONSE_INVALID", "已关联题注必须返回目标对象。")
                clean = {"blockId": block_id, "status": status, "targetBlockId": target_id}
                if "confidence" in item:
                    clean["confidence"] = cls._as_bounded_confidence(item["confidence"])
            else:
                if operation == "suggest_table_caption":
                    if candidate.get("tableType") != "data" or candidate.get("captionStatus") != "missing" or candidate.get("associationStatus") != "missing":
                        raise _error(
                            "FORMAT_SEMANTIC_CANDIDATE_OUT_OF_RANGE",
                            "缺表题建议候选不满足数据表和唯一缺题条件。",
                        )
                suggestion = item.get("suggestion")
                status = item.get("status")
                if status is not None and status not in {
                    "suggested",
                    "text_evidence_only",
                    "pixel_inspected",
                    "not_assessable",
                }:
                    raise _error("FORMAT_SEMANTIC_RESPONSE_INVALID", "题注建议状态无效。")
                if status == "pixel_inspected":
                    if not allow_pixel_inspection:
                        raise _error(
                            "IMAGE_SEMANTICS_DISABLED",
                            "图片语义总开关关闭时不能标记为已完成视觉判断。",
                        )
                    if candidate.get("pixelEvidenceVerified") is not True:
                        raise _error(
                            "IMAGE_PIXEL_EVIDENCE_NOT_VERIFIED",
                            "未验证实际图片像素，不能标记为已完成视觉判断。",
                        )
                if operation == "suggest_figure_caption" and suggestion:
                    expected_status = cls.validate_figure_caption_suggestion(
                        suggestion.strip(), candidate, allow_pixel_inspection
                    )
                    if status is None:
                        status = expected_status
                if status in {"not_assessable", "text_evidence_only"} and not suggestion:
                    suggestion = ""
                if not isinstance(suggestion, str) or (not suggestion.strip() and status not in {"not_assessable", "text_evidence_only"}):
                    raise _error("FORMAT_SEMANTIC_RESPONSE_INVALID", "题注建议不能为空。")
                if len(suggestion) > MAX_FORMAT_SEMANTIC_SUGGESTION_LENGTH:
                    raise _error("FORMAT_SEMANTIC_RESPONSE_INVALID", "题注建议不得超过 80 个字符。")
                if "\n" in suggestion or "\r" in suggestion or _MARKDOWN_PREFIX.search(suggestion) or _CAPTION_PREFIX.search(suggestion.strip()):
                    raise _error("FORMAT_SEMANTIC_RESPONSE_INVALID", "题注建议只能包含题注正文。")
                if operation == "suggest_table_caption" and suggestion.strip():
                    cls.validate_evidence_bound_suggestion(suggestion.strip(), candidate)
                clean = {"blockId": block_id, "suggestion": suggestion.strip()}
                if status is not None:
                    clean["status"] = status
            normalized.append(clean)
        if require_complete and len(normalized) != len(candidates):
            raise _error(
                "FORMAT_SEMANTIC_RESPONSE_INCOMPLETE",
                "格式语义验证响应未覆盖全部合成候选。",
            )
        return {
            "schemaVersion": FORMAT_SEMANTIC_SCHEMA_VERSION,
            "operation": operation,
            "snapshotBinding": dict(snapshot_binding),
            "items": normalized,
        }


class FormatSemanticExecutor:
    """Run one serial semantic batch with bounded retry and correction."""

    RETRYABLE_CODES = {
        "PROVIDER_TIMEOUT",
        "PROVIDER_UNREACHABLE",
        "PROVIDER_MID_STREAM_DISCONNECT",
        "MODEL_RATE_LIMITED",
        "DIFY_TIMEOUT",
        "DIFY_UNREACHABLE",
    }

    def __init__(
        self,
        call: Callable[[str, int], Any],
        used_calls: int = 0,
        task_auth: Optional[Dict] = None,
        phase_started_at: Optional[float] = None,
        monotonic_clock: Callable[[], float] = time.monotonic,
        allow_pixel_inspection: bool = False,
    ) -> None:
        self.call = call
        self.used_calls = int(used_calls)
        self.task_auth = task_auth or {}
        self.retry_count = 0
        self.correction_count = 0
        self.monotonic_clock = monotonic_clock
        self.allow_pixel_inspection = bool(allow_pixel_inspection)
        self.phase_started_at = (
            self.monotonic_clock() if phase_started_at is None else phase_started_at
        )

    def execute(
        self,
        operation: str,
        input_value: Any,
        candidates: Dict[str, Dict],
        snapshot_binding: Dict[str, str],
    ) -> Dict:
        if not FormatSemanticContract.is_allowed_operation(operation):
            raise _error("FORMAT_SEMANTIC_OPERATION_NOT_ALLOWED", "格式语义操作不在白名单内。")
        FormatSemanticContract.require_input_budget(input_value)
        output_budget = FormatSemanticContract.output_budget(self._task_auth())
        if not output_budget:
            output_budget = MAX_FORMAT_SEMANTIC_OUTPUT_TOKENS
        correction_used = False
        retry_used = False
        query = input_value if isinstance(input_value, str) else json.dumps(
            input_value, ensure_ascii=False, separators=(",", ":")
        )
        while True:
            if self.monotonic_clock() - self.phase_started_at >= 10 * 60:
                return self._failure("FORMAT_SEMANTIC_PHASE_TIMEOUT", "格式语义阶段已超过 10 分钟。")
            try:
                FormatSemanticContract.require_call_budget(self.used_calls)
                self.used_calls += 1
                response = self.call(query, output_budget)
                if self.monotonic_clock() - self.phase_started_at >= 10 * 60:
                    return self._failure("FORMAT_SEMANTIC_PHASE_TIMEOUT", "格式语义阶段已超过 10 分钟。")
                payload = self._payload_from_response(response)
                normalized = FormatSemanticContract.validate_response(
                    operation,
                    payload,
                    candidates,
                    snapshot_binding,
                    require_complete=True,
                    allow_pixel_inspection=self.allow_pixel_inspection,
                )
                return {
                    "payload": normalized,
                    "items": normalized["items"],
                    "usedCalls": self.used_calls,
                    "retryCount": self.retry_count,
                    "correctionCount": self.correction_count,
                }
            except AdapterError as exc:
                if exc.code in self.RETRYABLE_CODES and not retry_used:
                    retry_used = True
                    self.retry_count += 1
                    continue
                if exc.code == "FORMAT_SEMANTIC_RESPONSE_INVALID" or exc.code == "FORMAT_SEMANTIC_BINDING_INVALID":
                    if not correction_used:
                        correction_used = True
                        self.correction_count += 1
                        query = "{0}\n\n纠正要求：只返回符合 format_semantics.v1、当前 operation 和候选范围的完整 JSON。".format(query)
                        try:
                            FormatSemanticContract.require_input_budget(query)
                        except AdapterError as budget_error:
                            return self._failure(budget_error.code, budget_error.message)
                        continue
                return self._failure(exc.code, exc.message)
            except Exception:
                return self._failure(
                    "FORMAT_SEMANTIC_PROVIDER_ERROR",
                    "格式语义模型调用失败。",
                )

    def _task_auth(self) -> Dict:
        return self.task_auth

    def _failure(self, code: str, message: str) -> Dict:
        return {
            "payload": None,
            "items": None,
            "usedCalls": self.used_calls,
            "retryCount": self.retry_count,
            "correctionCount": self.correction_count,
            "error": AdapterError(code, message),
        }

    @staticmethod
    def _payload_from_response(response: Any) -> Dict:
        if isinstance(response, dict) and "result_json" in response:
            response = response.get("result_json")
        if isinstance(response, dict) and isinstance(response.get("answer"), str):
            response = response["answer"]
        if isinstance(response, str):
            try:
                response = json.loads(response)
            except json.JSONDecodeError as exc:
                raise _error("FORMAT_SEMANTIC_RESPONSE_INVALID", "格式语义响应不是有效 JSON。") from exc
        if not isinstance(response, dict):
            raise _error("FORMAT_SEMANTIC_RESPONSE_INVALID", "格式语义响应必须是 JSON 对象。")
        return response
