from copy import deepcopy
from typing import Callable, Dict, Optional, Tuple

from app.core.errors import AdapterError, ProviderTimeoutError
from app.core.models import WordDocumentRequest
from app.services.writing_policy import WritingPolicyService, get_writing_policy_service
from app.services.provider_client import (
    ProviderClient,
    get_default_document_review_prompt,
    merge_provider_debug,
)


def _policy_finding_issue(finding: object, category: str) -> Optional[Dict]:
    if not isinstance(finding, dict):
        return None
    evidence = str(finding.get("evidence", "")).strip()
    label = str(finding.get("label", "")).strip()
    message = str(finding.get("message", "")).strip()
    suggestion = str(finding.get("suggestion", "")).strip()
    if not label and not message:
        return None
    problem = "：".join(part for part in (label, message) if part)
    return {
        "category": category,
        "severity": (
            finding.get("severity")
            if finding.get("severity") in {"high", "medium", "low"}
            else ("low" if category == "expression" else "medium")
        ),
        "location": "写作规范检查",
        "originalText": evidence or None,
        "problem": problem,
        "suggestion": suggestion or "请按本次生效写作规范核对并调整该处表达。",
        "suggestedRewrite": None,
    }


def _policy_audit_issues(audit: Dict) -> list:
    issues = []
    for finding in audit.get("needsReview", []) or []:
        issue = _policy_finding_issue(finding, "professional")
        if issue is not None:
            issues.append(issue)
    for finding in audit.get("expressionSuggestions", []) or []:
        issue = _policy_finding_issue(finding, "expression")
        if issue is not None:
            issues.append(issue)
    return issues


def _review_issue_identity(issue: object) -> Tuple[str, str]:
    if not isinstance(issue, dict):
        return ("", "")
    category = str(issue.get("category", "")).strip().casefold()
    evidence = str(
        issue.get("originalText", issue.get("original_text", ""))
    ).strip().casefold()
    if evidence:
        return (category, evidence)
    return (category, str(issue.get("problem", "")).strip().casefold())


def _merge_review_issues(
    provider_issues: object,
    policy_issues: list,
) -> Tuple[list, int]:
    merged = list(provider_issues) if isinstance(provider_issues, list) else []
    seen = {_review_issue_identity(issue) for issue in merged}
    appended_count = 0
    for issue in policy_issues:
        key = _review_issue_identity(issue)
        if key not in seen:
            merged.append(issue)
            seen.add(key)
            appended_count += 1
    return merged, appended_count


def _summary_with_policy_findings(summary: object, finding_count: int) -> str:
    base = str(summary or "").strip()
    if finding_count <= 0:
        return base
    suffix = "另发现 %s 项写作规范问题。" % finding_count
    return "%s%s%s" % (base, " " if base else "", suffix)


class WordDocumentReviewer:
    def __init__(
        self,
        provider_client: Optional[ProviderClient] = None,
        writing_policy_service: Optional[WritingPolicyService] = None,
    ) -> None:
        self.provider_client = provider_client or ProviderClient()
        self.writing_policy_service = writing_policy_service

    def snapshot_task_auth(self) -> Optional[Dict]:
        resolver = getattr(self.provider_client, "resolve_task_auth", None)
        if not callable(resolver):
            return None
        try:
            return deepcopy(resolver("word.document_review"))
        except Exception as exc:
            raise AdapterError(
                "DOCUMENT_REVIEW_AUTH_SNAPSHOT_FAILED",
                "文档审查工作流配置暂时无法读取，请检查设置后重试。",
                status_code=503,
            ) from exc

    def review(
        self,
        request: WordDocumentRequest,
        trace_id: str,
        task_auth: Optional[Dict] = None,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> Dict:
        if progress_callback:
            progress_callback("preparing")
        source_text = request.content.plain_text.strip()
        if not source_text:
            source_text = "\n".join(
                paragraph.text for paragraph in request.content.paragraphs if paragraph.text.strip()
            ).strip()

        review_prompt = request.options.technical_review_prompt.strip()
        if not review_prompt:
            review_prompt = get_default_document_review_prompt(request.options.technical_document_type)

        writing_policy_service = self._get_writing_policy_service()
        writing_policy = writing_policy_service.prepare(
            "word.document_review",
            [source_text, request.options.technical_document_type, review_prompt],
            scene=request.writing_policy_scene,
        )
        try:
            if progress_callback:
                progress_callback("provider_processing")
            provider_kwargs = {
                "document_type": request.options.technical_document_type,
                "review_prompt": review_prompt,
                "writing_policy_block": writing_policy.prompt_block,
            }
            if task_auth is not None:
                provider_kwargs["task_auth"] = task_auth
            provider_result = self.provider_client.document_review(
                source_text, trace_id, **provider_kwargs
            )
        except ProviderTimeoutError:
            provider_result = self._provider_fallback(
                "模型后台文档审查未按时返回，adapter 已停止等待。",
                "请缩小审查范围后重试，或到“设置 - 最近一次任务诊断”查看 trace、provider 状态和模型后台返回情况。",
                "provider_timeout",
                "enterprise-dify-chat/timeout",
            )
        except AdapterError as exc:
            provider_result = self._provider_fallback(
                "模型后台文档审查请求失败，adapter 已返回诊断信息。",
                exc.message,
                exc.code.lower(),
                "enterprise-dify-chat/error",
            )
        finally:
            merge_provider_debug(trace_id, writing_policy.diagnostic_patch())
        if progress_callback:
            progress_callback("parsing")
        try:
            writing_policy_audit = writing_policy_service.audit_document_review(
                writing_policy,
                source_text,
            )
        except Exception:
            writing_policy_audit = {
                "enabled": bool(writing_policy.usage.get("applied", False)),
                "passed": False,
                "degraded": True,
                "degradedReason": "文档审查规范检查暂时不可用。",
                "summary": "文档审查规范检查暂时不可用，模型审查结果仍可正常查看。",
                "needsReview": [],
                "expressionSuggestions": [],
            }
        policy_issues = _policy_audit_issues(writing_policy_audit)
        issues, appended_policy_issue_count = _merge_review_issues(
            provider_result.get("issues", []),
            policy_issues,
        )
        return {
            "documentType": request.options.technical_document_type,
            "reviewPrompt": review_prompt,
            "scope": request.selection_mode,
            "summary": _summary_with_policy_findings(
                provider_result.get("summary", ""),
                appended_policy_issue_count,
            ),
            "issues": issues,
            "rawAnswer": provider_result.get("rawAnswer", ""),
            "parseFallbackReason": provider_result.get("parseFallbackReason", ""),
            "provider": provider_result.get("provider", "mock"),
            "writingPolicyUsage": writing_policy.usage,
            "writingPolicyAudit": writing_policy_audit,
        }

    def _get_writing_policy_service(self) -> WritingPolicyService:
        if self.writing_policy_service is not None:
            return self.writing_policy_service
        return get_writing_policy_service()

    def _provider_fallback(self, summary: str, detail: str, reason: str, provider: str) -> Dict:
        return {
            "summary": summary,
            "issues": [],
            "rawAnswer": detail,
            "parseFallbackReason": reason,
            "provider": provider,
        }
