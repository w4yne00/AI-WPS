import re
from typing import Callable, Dict, Optional, Tuple

from app.core.errors import AdapterError
from app.core.models import WordDocumentRequest
from app.services.writing_policy import (
    WritingPolicyService,
    explicitly_preserved_source_fragments,
    get_writing_policy_service,
)
from app.services.provider_client import ProviderClient, merge_provider_debug


_TEMPLATE_PRESERVATION_WORDS = ("保留", "保持", "沿用", "延续", "遵循", "仿照")
_NEGATED_PRESERVATION_PATTERN = re.compile(
    r"(?:不|不要|无需|无须|不必|不能|不得|取消|放弃).{0,3}"
    r"(?:保留|保持|沿用|延续|遵循|仿照)"
)
_PRESERVATION_CLAUSE_SEPARATOR = re.compile(
    r"(?:但是|但|而是|而要)|[，。；;！？!?\n]+"
)
_TEMPLATE_STRUCTURE_SCOPES = ("结构", "层次", "段落", "顺序", "路标")
_TEMPLATE_EXPRESSION_SCOPES = ("句式", "表达节奏")


def _affirmative_preservation_clauses(requirement: str) -> Tuple[str, ...]:
    clauses = (
        clause.strip()
        for clause in _PRESERVATION_CLAUSE_SEPARATOR.split(requirement)
    )
    return tuple(
        clause
        for clause in clauses
        if clause
        and not _NEGATED_PRESERVATION_PATTERN.search(clause)
        and any(word in clause for word in _TEMPLATE_PRESERVATION_WORDS)
    )


def _finding_is_explicitly_preserved(
    finding: object,
    template_text: str,
    preservation_clauses: Tuple[str, ...],
) -> bool:
    if not isinstance(finding, dict):
        return False
    evidence = str(finding.get("evidence", "")).strip()
    if not evidence:
        return False
    parts = [part.strip() for part in evidence.split("、") if part.strip()]
    evidence_is_from_template = evidence in template_text or (
        len(parts) > 1 and all(part in template_text for part in parts)
    )
    if not evidence_is_from_template:
        return False
    if any(
        evidence in clause
        or (len(parts) > 1 and all(part in clause for part in parts))
        for clause in preservation_clauses
    ):
        return True
    tier = str(finding.get("tier", "")).strip()
    if tier == "T3":
        scopes = _TEMPLATE_STRUCTURE_SCOPES
    elif tier in {"T1", "T2"}:
        scopes = _TEMPLATE_EXPRESSION_SCOPES
    else:
        scopes = ()
    return any(
        scope in clause
        for clause in preservation_clauses
        for scope in scopes
    )


def _suppress_preserved_template_structure_suggestions(
    audit: Dict,
    template_text: str,
    requirement: str,
) -> Dict:
    preservation_clauses = _affirmative_preservation_clauses(requirement)
    if not preservation_clauses:
        return audit
    suggestions = audit.get("expressionSuggestions")
    if not isinstance(suggestions, list):
        return audit
    retained = [
        finding
        for finding in suggestions
        if not _finding_is_explicitly_preserved(
            finding,
            template_text,
            preservation_clauses,
        )
    ]
    if len(retained) == len(suggestions):
        return audit
    filtered = dict(audit)
    filtered["expressionSuggestions"] = retained
    needs_review = filtered.get("needsReview")
    if not retained and not needs_review:
        filtered["passed"] = True
        filtered["summary"] = "已完成写作规范检查"
    return filtered


class WordSmartImitator:
    def __init__(
        self,
        provider_client: Optional[ProviderClient] = None,
        writing_policy_service: Optional[WritingPolicyService] = None,
    ) -> None:
        self.provider_client = provider_client or ProviderClient()
        self.writing_policy_service = writing_policy_service

    def snapshot_task_auth(self) -> Optional[Dict]:
        resolver = getattr(self.provider_client, "resolve_task_auth", None)
        return resolver("word.smart_imitation") if callable(resolver) else None

    def imitate(
        self,
        request: WordDocumentRequest,
        trace_id: str,
        task_auth: Optional[Dict] = None,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> Dict:
        if progress_callback:
            progress_callback("preparing")
        template_text = self._extract_template_text(request)
        requirement = request.options.imitation_requirement.strip()
        reference_material = request.options.imitation_reference_material.strip()

        if not template_text:
            raise AdapterError("SMART_IMITATION_TEMPLATE_REQUIRED", "请先提供仿写模板。", status_code=400)
        if not requirement:
            raise AdapterError("SMART_IMITATION_REQUIREMENT_REQUIRED", "请填写仿写需求。", status_code=400)

        writing_policy_service = self._get_writing_policy_service()
        writing_policy = writing_policy_service.prepare(
            "word.smart_imitation",
            [template_text, requirement, reference_material],
            scene=request.writing_policy_scene,
        )
        try:
            provider_kwargs = {"writing_policy_block": writing_policy.prompt_block}
            if task_auth is not None:
                provider_kwargs["task_auth"] = task_auth
            if progress_callback is not None:
                provider_kwargs["progress_callback"] = progress_callback
            provider_result = self.provider_client.smart_imitation(
                template_text,
                requirement,
                reference_material,
                trace_id,
                **provider_kwargs
            )
        finally:
            merge_provider_debug(trace_id, writing_policy.diagnostic_patch())
        rewritten_text = provider_result["rewrittenText"]
        if progress_callback:
            progress_callback("parsing")
        preservation_clauses = _affirmative_preservation_clauses(requirement)
        preserved_template_source = explicitly_preserved_source_fragments(
            template_text,
            preservation_clauses,
        )
        audit_source = "\n".join(
            part
            for part in (
                requirement,
                reference_material,
                preserved_template_source,
            )
            if part
        )
        try:
            writing_policy_audit = writing_policy_service.audit(
                writing_policy,
                audit_source,
                rewritten_text,
            )
        except Exception:
            writing_policy_audit = {
                "enabled": bool(writing_policy.usage.get("applied", False)),
                "passed": False,
                "degraded": True,
                "degradedReason": "写作规范检查暂时不可用。",
                "summary": "写作规范检查暂时不可用，结果仍可正常预览、复制。",
                "needsReview": [],
                "expressionSuggestions": [],
            }
        writing_policy_audit = _suppress_preserved_template_structure_suggestions(
            writing_policy_audit,
            template_text,
            requirement,
        )
        return {
            "originalText": template_text,
            "rewrittenText": rewritten_text,
            "rewriteMode": "imitate",
            "diffHints": [],
            "provider": provider_result.get("provider", "mock"),
            "writingPolicyUsage": writing_policy.usage,
            "writingPolicyAudit": writing_policy_audit,
        }

    def _get_writing_policy_service(self) -> WritingPolicyService:
        if self.writing_policy_service is not None:
            return self.writing_policy_service
        return get_writing_policy_service()

    def _extract_template_text(self, request: WordDocumentRequest) -> str:
        template_text = request.content.plain_text.strip()
        if not template_text:
            template_text = "\n".join(
                paragraph.text for paragraph in request.content.paragraphs if paragraph.text.strip()
            ).strip()
        return template_text
