import math
import os
import re
import threading
import time
from copy import deepcopy
from pathlib import Path
from typing import Callable, Dict, Optional, Sequence

from app.core.runtime_paths import resolve_runtime_paths

from .audit import (
    audit_document_review_writing_policy,
    audit_writing_policy_result,
)
from .matcher import build_match_result
from .models import WritingPolicyError, WritingPolicyMatchResult, public_usage
from .packs import WritingPolicyPackSnapshot, load_pack_snapshot
from .scenes import SCENE_LABELS, SCENE_PACK_IDS, resolve_scene
from .store import WritingPolicyStore


_ERROR_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_ITEM_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_MAX_DIAGNOSTIC_ITEM_IDS = 20
_PRESET_TASK_TYPES = {
    "word.smart_write": "smart_write",
    "word.smart_imitation": "smart_imitate",
    "word.document_review": "document_review",
}
_ORGANIZATION_TASK_TYPES = {
    value: key for key, value in _PRESET_TASK_TYPES.items()
}
_INITIALIZATION_BACKOFF_SECONDS = 5.0
_DEFAULT_PERFORMANCE_TARGET_MS = 100
_MAX_PERFORMANCE_TARGET_MS = 10000
_INITIALIZATION_CLOCK = time.monotonic
_SERVICE_LOCK = threading.Lock()
_SERVICES_BY_PATH = {}  # type: Dict[Path, WritingPolicyService]
_INITIALIZING_BY_PATH = {}  # type: Dict[Path, object]
_INITIALIZATION_FAILURES = {}  # type: Dict[Path, object]


def default_database_path() -> Path:
    configured = os.getenv("AI_WPS_WRITING_POLICY_DB", "").strip()
    if configured:
        return Path(configured)
    return resolve_runtime_paths().writing_policy_db_path


def _safe_error_code(error: Exception) -> str:
    if isinstance(error, WritingPolicyError):
        code = str(error.code or "")
        return code if _ERROR_CODE_RE.fullmatch(code) else "writing_policy_error"
    if isinstance(error, OSError):
        return "writing_policy_io_error"
    return "writing_policy_internal_error"


def _safe_item_ids(values: Sequence[str]):
    item_ids = []
    for value in values:
        if len(item_ids) >= _MAX_DIAGNOSTIC_ITEM_IDS:
            break
        if isinstance(value, str) and _ITEM_ID_RE.fullmatch(value):
            item_ids.append(value)
    return item_ids


def _safe_clock_value(clock: Callable[[], float]) -> Optional[float]:
    try:
        value = float(clock())
    except Exception:
        return None
    return value if math.isfinite(value) else None


def _initialization_now() -> float:
    value = _safe_clock_value(_INITIALIZATION_CLOCK)
    return value if value is not None else 0.0


def _elapsed_ms(started_at: Optional[float], finished_at: Optional[float]) -> int:
    if started_at is None or finished_at is None or finished_at < started_at:
        return 0
    return max(0, int(round((finished_at - started_at) * 1000)))


def _nonnegative_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return max(0, value)


def _performance_target_ms(configured: Optional[int]) -> int:
    value = configured
    if value is None:
        try:
            value = int(
                os.getenv(
                    "AI_WPS_WRITING_POLICY_PERFORMANCE_TARGET_MS",
                    str(_DEFAULT_PERFORMANCE_TARGET_MS),
                )
            )
        except (TypeError, ValueError):
            value = _DEFAULT_PERFORMANCE_TARGET_MS
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 1
        or value > _MAX_PERFORMANCE_TARGET_MS
    ):
        return _DEFAULT_PERFORMANCE_TARGET_MS
    return value


def _diagnostic_patch(
    *,
    applied: bool,
    degraded: bool,
    error_code: str,
    term_count: int,
    style_count: int,
    truncated_count: int,
    elapsed_ms: int,
    item_ids: Sequence[str],
    preset_versions: Sequence[Dict[str, str]] = (),
) -> Dict[str, object]:
    patch = {
        "writingPolicyApplied": bool(applied),
        "writingPolicyDegraded": bool(degraded),
        "writingPolicyErrorCode": error_code,
        "writingPolicyTermCount": _nonnegative_int(term_count),
        "writingPolicyStyleCount": _nonnegative_int(style_count),
        "writingPolicyTruncatedCount": _nonnegative_int(truncated_count),
        "writingPolicyElapsedMs": _nonnegative_int(elapsed_ms),
        "writingPolicyItemIds": _safe_item_ids(item_ids),
    }
    safe_versions = []
    for value in preset_versions:
        pack_id = str(value.get("packId") or "")
        version = str(value.get("version") or "")
        if (
            len(safe_versions) < 4
            and re.fullmatch(r"[a-z][a-z0-9.-]{2,63}", pack_id)
            and re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version)
        ):
            safe_versions.append({"packId": pack_id, "version": version})
    if safe_versions:
        patch["writingPolicyPresetVersions"] = safe_versions
    return patch


class WritingPolicyService:
    def __init__(
        self,
        store: object,
        clock: Optional[Callable[[], float]] = None,
        pack_snapshot: Optional[WritingPolicyPackSnapshot] = None,
        performance_target_ms: Optional[int] = None,
    ):
        self.store = store
        self.pack_snapshot = (
            pack_snapshot
            if pack_snapshot is not None
            else load_pack_snapshot(strict=False)
        )
        self._clock = clock or time.monotonic
        self._performance_target_ms = _performance_target_ms(
            performance_target_ms
        )
        self._diagnostic_lock = threading.Lock()
        initial_pack_issue = (
            self.pack_snapshot.issues[0]
            if self.pack_snapshot.issues
            else None
        )
        self._last_diagnostic = dict(
            self._with_performance(
                _diagnostic_patch(
                    applied=False,
                    degraded=initial_pack_issue is not None,
                    error_code=(
                        initial_pack_issue.error_code
                        if initial_pack_issue is not None
                        else ""
                    ),
                    term_count=0,
                    style_count=0,
                    truncated_count=0,
                    elapsed_ms=0,
                    item_ids=(),
                    preset_versions=tuple(
                        {
                            "packId": pack.pack_id,
                            "version": pack.version,
                        }
                        for pack in self.pack_snapshot.packs
                    ),
                ),
                0,
            ),
            stage=(
                "pack_load_degraded"
                if initial_pack_issue is not None
                else "idle"
            ),
        )

    def prepare(
        self,
        task_scope: str,
        source_parts: Sequence[str],
        scene: str = "auto",
    ) -> WritingPolicyMatchResult:
        started_at = _safe_clock_value(self._clock)
        try:
            resolution = resolve_scene(scene, source_parts)
            if resolution.resolved_scene == "disabled":
                usage = public_usage(
                    applied=False,
                    terms=0,
                    styles=0,
                    truncated=0,
                    matched_items=[],
                )
                usage.update(self._scene_usage(resolution, ()))
                matched = WritingPolicyMatchResult("", usage, ())
                selected_packs = ()
            else:
                terms, styles = self.store.enabled_items(
                    task_scope,
                    resolution.resolved_scene,
                )
                preset_operations = self._preset_operations()
                selected_packs = self._selected_packs(
                    task_scope,
                    resolution,
                )
                for preset in reversed(selected_packs):
                    pack_scene = (
                        "yangqi"
                        if preset["packId"] == "yangqi-tech-writing-base"
                        else resolution.resolved_scene
                    )
                    preset_terms, preset_styles = self.pack_snapshot.matcher_items(
                        preset["packId"],
                        _PRESET_TASK_TYPES[task_scope],
                        pack_scene,
                    )
                    pack_items = self.pack_snapshot.public_items(
                        preset["packId"]
                    )
                    preset_terms = self._effective_preset_terms(
                        preset_terms,
                        preset_operations,
                        pack_items,
                    )
                    preset_styles = self._effective_preset_rules(
                        preset_styles,
                        preset_operations,
                        pack_items,
                        task_scope,
                        pack_scene,
                    )
                    terms = preset_terms + list(terms)
                    styles = preset_styles + list(styles)
                matched = build_match_result(
                    terms,
                    styles,
                    task_scope,
                    source_parts,
                )
        except Exception as error:
            return self._degraded_result(error, started_at)

        elapsed_ms = _elapsed_ms(started_at, _safe_clock_value(self._clock))
        usage = matched.usage
        usage.update(self._scene_usage(resolution, selected_packs))
        pack_issues = self._selected_pack_issues(task_scope, resolution)
        if pack_issues:
            usage["degraded"] = True
            usage["degradedReason"] = "写作规范暂未完整应用，已继续处理。"
        patch = _diagnostic_patch(
            applied=bool(usage.get("applied", False)),
            degraded=bool(usage.get("degraded", False)),
            error_code=pack_issues[0].error_code if pack_issues else "",
            term_count=_nonnegative_int(usage.get("termMatchCount", 0)),
            style_count=_nonnegative_int(usage.get("styleRuleCount", 0)),
            truncated_count=_nonnegative_int(usage.get("truncatedCount", 0)),
            elapsed_ms=elapsed_ms,
            item_ids=matched.matched_item_ids,
            preset_versions=usage.get("presetVersions", ()),
        )
        self._record_diagnostic(
            "prepared_degraded" if pack_issues else "prepared",
            self._with_performance(patch, elapsed_ms),
        )
        return WritingPolicyMatchResult(
            matched.prompt_block,
            usage,
            matched.matched_item_ids,
            patch,
            audit_terms=matched.audit_terms,
        )

    def audit(
        self,
        match_result: WritingPolicyMatchResult,
        source_text: str,
        result_text: str,
    ) -> Dict[str, object]:
        started_at = _safe_clock_value(self._clock)
        usage = match_result.usage
        if not bool(usage.get("applied", False)):
            audit = {
                "enabled": False,
                "passed": True,
                "degraded": False,
                "degradedReason": "",
                "summary": "本次未使用写作规范检查",
                "needsReview": [],
                "expressionSuggestions": [],
            }
            self._record_audit_diagnostic(
                match_result,
                started_at,
                stage="audit_skipped",
            )
            return audit
        try:
            audit = audit_writing_policy_result(
                source_text,
                result_text,
                match_result.audit_terms,
            )
        except Exception as error:
            audit = {
                "enabled": True,
                "passed": False,
                "degraded": True,
                "degradedReason": "写作规范检查暂时不可用。",
                "summary": "写作规范检查暂时不可用，结果仍可正常预览、复制或写回。",
                "needsReview": [],
                "expressionSuggestions": [],
            }
            self._record_audit_diagnostic(
                match_result,
                started_at,
                stage="audit_degraded",
                error=error,
            )
            return audit
        audit["enabled"] = True
        self._record_audit_diagnostic(
            match_result,
            started_at,
            stage="audited",
        )
        return audit

    def audit_document_review(
        self,
        match_result: WritingPolicyMatchResult,
        source_text: str,
    ) -> Dict[str, object]:
        started_at = _safe_clock_value(self._clock)
        usage = match_result.usage
        if not bool(usage.get("applied", False)):
            audit = {
                "enabled": False,
                "passed": True,
                "degraded": False,
                "degradedReason": "",
                "summary": "本次未使用文档审查规范检查",
                "needsReview": [],
                "expressionSuggestions": [],
            }
            self._record_audit_diagnostic(
                match_result,
                started_at,
                stage="audit_skipped",
            )
            return audit
        try:
            audit = audit_document_review_writing_policy(
                source_text,
                match_result.audit_terms,
            )
        except Exception as error:
            audit = {
                "enabled": True,
                "passed": False,
                "degraded": True,
                "degradedReason": "文档审查规范检查暂时不可用。",
                "summary": "文档审查规范检查暂时不可用，模型审查结果仍可正常查看。",
                "needsReview": [],
                "expressionSuggestions": [],
            }
            self._record_audit_diagnostic(
                match_result,
                started_at,
                stage="audit_degraded",
                error=error,
            )
            return audit
        audit["enabled"] = True
        self._record_audit_diagnostic(
            match_result,
            started_at,
            stage="audited",
        )
        return audit

    def list_packs(self):
        return self.pack_snapshot.public_packs()

    def list_preset_items(
        self, pack_id: str, item_type: Optional[str] = None
    ):
        items = self.pack_snapshot.public_items(pack_id)
        if item_type is not None:
            items = [
                item for item in items if item.get("type") == item_type
            ]
        operations = self._preset_operations()
        result = []
        for baseline_item in items:
            item = deepcopy(baseline_item)
            item["baseline"] = deepcopy(baseline_item)
            operation = operations.get(str(item.get("id") or ""))
            item["organizationState"] = "preset"
            item["effective"] = bool(item.get("defaultEnabled", False))
            item["presetOperation"] = None
            if operation is not None:
                item["presetOperation"] = deepcopy(operation)
                if operation["operation"] == "disabled":
                    item["organizationState"] = "disabled"
                    item["effective"] = False
                elif operation["operation"] == "override":
                    item.update(deepcopy(operation["payload"]))
                    item["id"] = baseline_item["id"]
                    item["type"] = baseline_item["type"]
                    item["packId"] = baseline_item["packId"]
                    item["packName"] = baseline_item["packName"]
                    item["packVersion"] = baseline_item["packVersion"]
                    item["source"] = deepcopy(baseline_item["source"])
                    item["organizationState"] = "overridden"
                    item["effective"] = True
            result.append(item)
        return result

    def put_preset_operation(
        self,
        preset_entry_id: str,
        operation: str,
        payload: Dict[str, object],
    ) -> Dict[str, object]:
        baseline = self._find_preset_item(preset_entry_id)
        item_type = str(baseline.get("type") or "")
        if operation == "disabled":
            operation_payload = None
        elif operation == "override":
            if item_type == "term":
                operation_payload = self._preset_term_payload(baseline)
            elif item_type in ("style", "anti_template"):
                operation_payload = self._preset_rule_payload(baseline)
            else:
                raise WritingPolicyError(
                    "invalid_writing_policy_type",
                    "预置规范类型无效。",
                )
            operation_payload.update(dict(payload or {}))
            operation_payload["type"] = item_type
            operation_payload["enabled"] = True
        else:
            raise WritingPolicyError(
                "invalid_preset_operation",
                "预置操作必须为 override 或 disabled。",
            )
        return self.store.upsert_preset_operation(
            preset_entry_id,
            str(baseline["packId"]),
            item_type,
            operation,
            operation_payload,
        )

    def restore_preset_operation(
        self, preset_entry_id: str
    ) -> Dict[str, object]:
        return self.store.restore_preset_operation(preset_entry_id)

    def _find_preset_item(self, preset_entry_id: str) -> Dict[str, object]:
        for pack in self.pack_snapshot.public_packs():
            for item in self.pack_snapshot.public_items(pack["packId"]):
                if item.get("id") == preset_entry_id:
                    return item
        raise WritingPolicyError(
            "writing_policy_preset_item_not_found",
            "未找到指定预置规范条目。",
        )

    def _preset_operations(self) -> Dict[str, Dict[str, object]]:
        list_operations = getattr(
            self.store, "list_preset_operations", None
        )
        if not callable(list_operations):
            return {}
        return {
            operation["presetEntryId"]: operation
            for operation in list_operations()
        }

    @staticmethod
    def _priority_label(item: Dict[str, object]) -> str:
        numeric_priority = int(item.get("priority", 0))
        return (
            "high"
            if numeric_priority >= 67
            else "medium"
            if numeric_priority >= 34
            else "low"
        )

    @staticmethod
    def _preset_term_payload(item: Dict[str, object]) -> Dict[str, object]:
        return {
            "type": "term",
            "scope": "global",
            "category": str(item.get("category") or ""),
            "preferredText": str(item.get("preferredText") or ""),
            "aliases": list(item.get("aliases") or []),
            "forbiddenVariants": list(
                item.get("forbiddenVariants") or []
            ),
            "definition": str(item.get("definition") or ""),
            "contextKeywords": list(item.get("contextKeywords") or []),
            "priority": WritingPolicyService._priority_label(item),
            "enabled": True,
            "note": "",
        }

    @staticmethod
    def _preset_rule_payload(item: Dict[str, object]) -> Dict[str, object]:
        task_types = [
            _ORGANIZATION_TASK_TYPES[value]
            for value in item.get("taskTypes", ())
            if value in _ORGANIZATION_TASK_TYPES
        ]
        return {
            "type": str(item.get("type") or "style"),
            "scope": "global",
            "taskTypes": task_types or list(_PRESET_TASK_TYPES),
            "sceneIds": list(item.get("sceneIds") or ()),
            "name": str(item.get("name") or ""),
            "ruleText": str(item.get("ruleText") or ""),
            "positiveExample": str(item.get("positiveExample") or ""),
            "negativeExample": str(item.get("negativeExample") or ""),
            "contextKeywords": list(item.get("contextKeywords") or []),
            "alwaysApply": True,
            "priority": WritingPolicyService._priority_label(item),
            "enabled": True,
            "note": "",
        }

    @staticmethod
    def _effective_preset_terms(
        terms,
        operations: Dict[str, Dict[str, object]],
        pack_items=(),
    ):
        effective = []
        included_ids = set()
        for baseline in terms:
            baseline_id = str(baseline.get("id") or "")
            included_ids.add(baseline_id)
            operation = operations.get(baseline_id)
            if operation is not None and operation["operation"] == "disabled":
                continue
            if operation is not None and operation["operation"] == "override":
                effective.append(
                    WritingPolicyService._preset_override_matcher_item(
                        baseline, operation
                    )
                )
            else:
                effective.append(baseline)
        for baseline in pack_items:
            baseline_id = str(baseline.get("id") or "")
            operation = operations.get(baseline_id)
            if (
                baseline_id in included_ids
                or baseline.get("type") != "term"
                or operation is None
                or operation["operation"] != "override"
            ):
                continue
            effective.append(
                WritingPolicyService._preset_override_matcher_item(
                    baseline, operation
                )
            )
        return effective

    @staticmethod
    def _effective_preset_rules(
        rules,
        operations: Dict[str, Dict[str, object]],
        pack_items,
        task_scope: str,
        scene_id: str,
    ):
        effective = []
        included_ids = set()
        for baseline in rules:
            baseline_id = str(baseline.get("id") or "")
            included_ids.add(baseline_id)
            operation = operations.get(baseline_id)
            if operation is None:
                effective.append(baseline)
                continue
            if operation["operation"] == "disabled":
                continue
            payload = operation["payload"]
            if (
                task_scope in payload.get("taskTypes", ())
                and scene_id in payload.get("sceneIds", ())
            ):
                effective.append(
                    WritingPolicyService._preset_rule_override_matcher_item(
                        baseline,
                        operation,
                        task_scope,
                    )
                )
        for baseline in pack_items:
            baseline_id = str(baseline.get("id") or "")
            operation = operations.get(baseline_id)
            if (
                baseline_id in included_ids
                or baseline.get("type") not in ("style", "anti_template")
                or operation is None
                or operation["operation"] != "override"
            ):
                continue
            payload = operation["payload"]
            if (
                task_scope not in payload.get("taskTypes", ())
                or scene_id not in payload.get("sceneIds", ())
            ):
                continue
            effective.append(
                WritingPolicyService._preset_rule_override_matcher_item(
                    baseline,
                    operation,
                    task_scope,
                )
            )
        return effective

    @staticmethod
    def _preset_override_matcher_item(baseline, operation):
        item = deepcopy(operation["payload"])
        item.update(
            {
                "id": baseline["id"],
                "type": "term",
                "scope": "global",
                "enabled": True,
                "layer": "organization",
                "packId": baseline.get("packId"),
                "packVersion": baseline.get("packVersion"),
                "presetOperation": "override",
            }
        )
        return item

    @staticmethod
    def _preset_rule_override_matcher_item(
        baseline,
        operation,
        task_scope: str,
    ):
        item = deepcopy(operation["payload"])
        item.update(
            {
                "id": baseline["id"],
                "type": baseline["type"],
                "scope": task_scope,
                "enabled": True,
                "layer": "organization",
                "packId": baseline.get("packId"),
                "packVersion": baseline.get("packVersion"),
                "presetOperation": "override",
            }
        )
        return item

    def _selected_packs(self, task_scope: str, resolution):
        if task_scope not in _PRESET_TASK_TYPES:
            return ()
        packs_by_id = {
            pack["packId"]: pack
            for pack in self.pack_snapshot.public_packs()
        }
        pack_ids = SCENE_PACK_IDS.get(resolution.resolved_scene, ())
        if resolution.auto_fallback:
            pack_ids = ("yangqi-tech-writing-base",)
        return tuple(
            packs_by_id[pack_id]
            for pack_id in pack_ids
            if pack_id in packs_by_id
        )

    def _selected_pack_issues(self, task_scope: str, resolution):
        if (
            task_scope not in _PRESET_TASK_TYPES
            or resolution.resolved_scene == "disabled"
        ):
            return ()
        pack_ids = SCENE_PACK_IDS.get(resolution.resolved_scene, ())
        if resolution.auto_fallback:
            pack_ids = ("yangqi-tech-writing-base",)
        return tuple(
            issue
            for issue in self.pack_snapshot.issues
            if issue.pack_id in pack_ids or issue.pack_id == "preset-packs"
        )

    def _scene_usage(self, resolution, selected_packs):
        result = {
            "requestedScene": resolution.requested_scene,
            "scene": resolution.resolved_scene,
            "sceneLabel": SCENE_LABELS.get(
                resolution.resolved_scene,
                SCENE_LABELS["yangqi"],
            ),
            "autoFallback": bool(resolution.auto_fallback),
            "packNames": [pack["name"] for pack in selected_packs],
            "presetVersions": [
                {
                    "packId": pack["packId"],
                    "version": pack["version"],
                }
                for pack in selected_packs
            ],
        }
        if len(selected_packs) == 1:
            result["packName"] = selected_packs[0]["name"]
            result["presetVersion"] = selected_packs[0]["version"]
        return result

    def diagnostics(self) -> Dict[str, object]:
        with self._diagnostic_lock:
            return deepcopy(self._last_diagnostic)

    def _record_audit_diagnostic(
        self,
        match_result: WritingPolicyMatchResult,
        started_at: Optional[float],
        *,
        stage: str,
        error: Optional[Exception] = None,
    ) -> None:
        audit_elapsed_ms = _elapsed_ms(
            started_at,
            _safe_clock_value(self._clock),
        )
        patch = match_result.diagnostic_patch()
        prepare_elapsed_ms = _nonnegative_int(
            patch.get("writingPolicyElapsedMs", 0)
        )
        patch["writingPolicyAuditElapsedMs"] = audit_elapsed_ms
        patch["writingPolicyTotalElapsedMs"] = (
            prepare_elapsed_ms + audit_elapsed_ms
        )
        if error is not None:
            patch["writingPolicyDegraded"] = True
            patch["writingPolicyErrorCode"] = _safe_error_code(error)
        self._record_diagnostic(
            stage,
            self._with_performance(
                patch,
                prepare_elapsed_ms + audit_elapsed_ms,
            ),
        )

    def _with_performance(
        self,
        patch: Dict[str, object],
        total_elapsed_ms: int,
    ) -> Dict[str, object]:
        diagnostic = deepcopy(patch)
        elapsed_ms = _nonnegative_int(total_elapsed_ms)
        diagnostic["writingPolicyPerformanceTargetMs"] = (
            self._performance_target_ms
        )
        diagnostic["writingPolicyWithinTarget"] = (
            elapsed_ms <= self._performance_target_ms
        )
        return diagnostic

    def _degraded_result(
        self,
        error: Exception,
        started_at: Optional[float],
    ) -> WritingPolicyMatchResult:
        elapsed_ms = _elapsed_ms(started_at, _safe_clock_value(self._clock))
        error_code = _safe_error_code(error)
        usage = public_usage(
            applied=False,
            terms=0,
            styles=0,
            truncated=0,
            matched_items=[],
            degraded=True,
            degraded_reason="写作规范暂未应用，已继续处理。",
        )
        patch = _diagnostic_patch(
            applied=False,
            degraded=True,
            error_code=error_code,
            term_count=0,
            style_count=0,
            truncated_count=0,
            elapsed_ms=elapsed_ms,
            item_ids=(),
        )
        self._record_diagnostic(
            "degraded",
            self._with_performance(patch, elapsed_ms),
        )
        return WritingPolicyMatchResult("", usage, (), patch)

    def _record_diagnostic(self, stage: str, patch: Dict[str, object]) -> None:
        diagnostic = dict(deepcopy(patch), stage=stage)
        with self._diagnostic_lock:
            self._last_diagnostic = diagnostic


class _UnavailableStore:
    def __init__(self, error_code: str):
        self.error_code = error_code

    def enabled_items(self, task_scope: str, scene_id: Optional[str] = None):
        del scene_id
        raise WritingPolicyError(
            self.error_code,
            "写作规范库暂时不可用。",
        )


def _degraded_service(error: Exception) -> WritingPolicyService:
    return WritingPolicyService(
        store=_UnavailableStore(_safe_error_code(error)),
        pack_snapshot=WritingPolicyPackSnapshot(()),
    )


def _initializing_service() -> WritingPolicyService:
    return _degraded_service(
        WritingPolicyError(
            "writing_policy_initializing",
            "写作规范库正在初始化。",
        )
    )


def _release_initialization(db_path: Path, token: object) -> None:
    with _SERVICE_LOCK:
        if _INITIALIZING_BY_PATH.get(db_path) is token:
            del _INITIALIZING_BY_PATH[db_path]


def get_writing_policy_service() -> WritingPolicyService:
    try:
        db_path = default_database_path().expanduser().resolve()
    except Exception as error:
        return _degraded_service(error)

    now = _initialization_now()
    token = object()
    with _SERVICE_LOCK:
        service = _SERVICES_BY_PATH.get(db_path)
        if service is not None:
            return service

        failure = _INITIALIZATION_FAILURES.get(db_path)
        if failure is not None:
            retry_after, failed_service = failure
            if now < retry_after:
                return failed_service
            del _INITIALIZATION_FAILURES[db_path]

        if db_path in _INITIALIZING_BY_PATH:
            return _initializing_service()
        _INITIALIZING_BY_PATH[db_path] = token

    try:
        try:
            store = WritingPolicyStore(db_path)
            service = WritingPolicyService(store=store)
        except Exception as error:
            failed_service = _degraded_service(error)
            retry_after = _initialization_now() + _INITIALIZATION_BACKOFF_SECONDS
            with _SERVICE_LOCK:
                if _INITIALIZING_BY_PATH.get(db_path) is token:
                    _INITIALIZATION_FAILURES[db_path] = (
                        retry_after,
                        failed_service,
                    )
            return failed_service

        with _SERVICE_LOCK:
            if _INITIALIZING_BY_PATH.get(db_path) is token:
                _INITIALIZATION_FAILURES.pop(db_path, None)
                cached_service = _SERVICES_BY_PATH.get(db_path)
                if cached_service is None:
                    _SERVICES_BY_PATH[db_path] = service
                else:
                    service = cached_service
        return service
    finally:
        _release_initialization(db_path, token)


def _reset_writing_policy_services() -> None:
    with _SERVICE_LOCK:
        _SERVICES_BY_PATH.clear()
        _INITIALIZATION_FAILURES.clear()
        _INITIALIZING_BY_PATH.clear()
