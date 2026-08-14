"""Boundaries for model-assisted Word format semantics.

The deterministic formatter owns compliance decisions.  This module only
defines the small, auditable contract that a model may supplement.
"""

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
_MARKDOWN_PREFIX = re.compile(r"(^|\s)([#>*`]|[-+]\s|\d+[.)]\s)")


def _error(code: str, message: str, status_code: int = 409) -> AdapterError:
    return AdapterError(code, message, status_code=status_code)


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
        return {"blockId", "suggestion"}

    @staticmethod
    def _as_bounded_confidence(value: Any) -> float:
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            raise _error("FORMAT_SEMANTIC_RESPONSE_INVALID", "模型置信度无效。")
        if not 0 <= confidence <= 1:
            raise _error("FORMAT_SEMANTIC_RESPONSE_INVALID", "模型置信度超出范围。")
        return confidence

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
    ) -> Dict:
        if not cls.is_allowed_operation(operation):
            raise _error("FORMAT_SEMANTIC_OPERATION_NOT_ALLOWED", "格式语义操作不在白名单内。")
        if not isinstance(payload, dict):
            raise _error("FORMAT_SEMANTIC_RESPONSE_INVALID", "格式语义响应必须是 JSON 对象。")
        allowed_payload_keys = {"schemaVersion", "operation", "snapshotBinding", "items"}
        if set(payload) - allowed_payload_keys:
            raise _error("FORMAT_SEMANTIC_RESPONSE_INVALID", "格式语义响应包含未声明字段。")
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
        for item in items:
            if not isinstance(item, dict):
                raise _error("FORMAT_SEMANTIC_RESPONSE_INVALID", "格式语义响应条目格式无效。")
            allowed_item_keys = cls._allowed_item_keys(operation)
            if set(item) - allowed_item_keys:
                raise _error("FORMAT_SEMANTIC_RESPONSE_INVALID", "格式语义条目包含未声明字段。")
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
                suggestion = item.get("suggestion")
                if not isinstance(suggestion, str) or not suggestion.strip():
                    raise _error("FORMAT_SEMANTIC_RESPONSE_INVALID", "题注建议不能为空。")
                if len(suggestion) > MAX_FORMAT_SEMANTIC_SUGGESTION_LENGTH:
                    raise _error("FORMAT_SEMANTIC_RESPONSE_INVALID", "题注建议不得超过 80 个字符。")
                if "\n" in suggestion or "\r" in suggestion or _MARKDOWN_PREFIX.search(suggestion):
                    raise _error("FORMAT_SEMANTIC_RESPONSE_INVALID", "题注建议只能包含题注正文。")
                clean = {"blockId": block_id, "suggestion": suggestion.strip()}
            normalized.append(clean)
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
    ) -> None:
        self.call = call
        self.used_calls = int(used_calls)
        self.task_auth = task_auth or {}
        self.retry_count = 0
        self.correction_count = 0
        self.monotonic_clock = monotonic_clock
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
                    operation, payload, candidates, snapshot_binding
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
