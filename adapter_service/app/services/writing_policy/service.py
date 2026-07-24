import math
import os
import re
import threading
import time
from copy import deepcopy
from pathlib import Path
from typing import Callable, Dict, Optional, Sequence

from .audit import audit_writing_policy_result
from .matcher import build_match_result
from .models import WritingPolicyError, WritingPolicyMatchResult, public_usage
from .packs import WritingPolicyPackSnapshot, load_pack_snapshot
from .scenes import SCENE_LABELS, SCENE_PACK_IDS, resolve_scene
from .store import WritingPolicyStore


_ERROR_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_ITEM_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_MAX_DIAGNOSTIC_ITEM_IDS = 20
_INITIALIZATION_BACKOFF_SECONDS = 5.0
_INITIALIZATION_CLOCK = time.monotonic
_SERVICE_LOCK = threading.Lock()
_SERVICES_BY_PATH = {}  # type: Dict[Path, WritingPolicyService]
_INITIALIZING_BY_PATH = {}  # type: Dict[Path, object]
_INITIALIZATION_FAILURES = {}  # type: Dict[Path, object]


def default_database_path() -> Path:
    configured = os.getenv("AI_WPS_WRITING_POLICY_DB", "").strip()
    if configured:
        return Path(configured)
    return (
        Path(__file__).resolve().parents[4]
        / "run"
        / "writing_policies.db"
    )


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
) -> Dict[str, object]:
    return {
        "writingPolicyApplied": bool(applied),
        "writingPolicyDegraded": bool(degraded),
        "writingPolicyErrorCode": error_code,
        "writingPolicyTermCount": _nonnegative_int(term_count),
        "writingPolicyStyleCount": _nonnegative_int(style_count),
        "writingPolicyTruncatedCount": _nonnegative_int(truncated_count),
        "writingPolicyElapsedMs": _nonnegative_int(elapsed_ms),
        "writingPolicyItemIds": _safe_item_ids(item_ids),
    }


class WritingPolicyService:
    def __init__(
        self,
        store: object,
        clock: Optional[Callable[[], float]] = None,
        pack_snapshot: Optional[WritingPolicyPackSnapshot] = None,
    ):
        self.store = store
        self.pack_snapshot = (
            pack_snapshot if pack_snapshot is not None else load_pack_snapshot()
        )
        self._clock = clock or time.monotonic
        self._diagnostic_lock = threading.Lock()
        self._last_diagnostic = dict(
            _diagnostic_patch(
                applied=False,
                degraded=False,
                error_code="",
                term_count=0,
                style_count=0,
                truncated_count=0,
                elapsed_ms=0,
                item_ids=(),
            ),
            stage="idle",
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
                terms, styles = self.store.enabled_items(task_scope)
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
                        "smart_write",
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
        patch = _diagnostic_patch(
            applied=bool(usage.get("applied", False)),
            degraded=bool(usage.get("degraded", False)),
            error_code="",
            term_count=_nonnegative_int(usage.get("termMatchCount", 0)),
            style_count=_nonnegative_int(usage.get("styleRuleCount", 0)),
            truncated_count=_nonnegative_int(usage.get("truncatedCount", 0)),
            elapsed_ms=elapsed_ms,
            item_ids=matched.matched_item_ids,
        )
        self._record_diagnostic("prepared", patch)
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
        usage = match_result.usage
        if not bool(usage.get("applied", False)):
            return {
                "enabled": False,
                "passed": True,
                "degraded": False,
                "degradedReason": "",
                "summary": "本次未使用写作规范检查",
                "needsReview": [],
                "expressionSuggestions": [],
            }
        try:
            audit = audit_writing_policy_result(
                source_text,
                result_text,
                match_result.audit_terms,
            )
        except Exception:
            return {
                "enabled": True,
                "passed": False,
                "degraded": True,
                "degradedReason": "写作规范检查暂时不可用。",
                "summary": "写作规范检查暂时不可用，结果仍可正常预览、复制或写回。",
                "needsReview": [],
                "expressionSuggestions": [],
            }
        audit["enabled"] = True
        return audit

    def list_packs(self):
        return self.pack_snapshot.public_packs()

    def list_preset_items(self, pack_id: str):
        return self.pack_snapshot.public_items(pack_id)

    def _selected_packs(self, task_scope: str, resolution):
        if task_scope != "word.smart_write":
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
            degraded_reason="写作规范服务暂时不可用，已跳过写作规范增强。",
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
        self._record_diagnostic("degraded", patch)
        return WritingPolicyMatchResult("", usage, (), patch)

    def _record_diagnostic(self, stage: str, patch: Dict[str, object]) -> None:
        diagnostic = dict(deepcopy(patch), stage=stage)
        with self._diagnostic_lock:
            self._last_diagnostic = diagnostic


class _UnavailableStore:
    def __init__(self, error_code: str):
        self.error_code = error_code

    def enabled_items(self, task_scope: str):
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
