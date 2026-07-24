from typing import Dict, List, Optional

from app.core.models import WordDocumentRequest
from app.services.writing_policy import WritingPolicyService, get_writing_policy_service
from app.services.provider_client import ProviderClient, merge_provider_debug


class WordRewriter:
    def __init__(
        self,
        provider_client: Optional[ProviderClient] = None,
        writing_policy_service: Optional[WritingPolicyService] = None,
    ) -> None:
        self.provider_client = provider_client or ProviderClient()
        self.writing_policy_service = writing_policy_service

    def rewrite(self, request: WordDocumentRequest, trace_id: str, mode: str = "rewrite") -> Dict:
        source_text = self._extract_source_text(request)

        provider_result = self.provider_client.rewrite(
            source_text,
            mode,
            trace_id,
            user_instruction=request.options.user_instruction,
            style=request.options.rewrite_style,
            focus=request.options.focus_point,
            length=request.options.length_mode,
        )
        rewritten_text = provider_result["rewrittenText"]
        return {
            "originalText": source_text,
            "rewrittenText": rewritten_text,
            "rewriteMode": mode,
            "diffHints": self._build_diff_hints(source_text, rewritten_text),
            "provider": provider_result.get("provider", "mock"),
        }

    def smart_write(self, request: WordDocumentRequest, trace_id: str) -> Dict:
        source_text = self._extract_source_text(request)
        action = request.options.rewrite_action or "rewrite"
        writing_policy_service = self._get_writing_policy_service()
        writing_policy = writing_policy_service.prepare(
            "word.smart_write",
            [source_text, request.options.user_instruction],
            scene=request.writing_policy_scene,
        )
        try:
            provider_result = self.provider_client.smart_write(
                source_text,
                action,
                trace_id,
                user_prompt=request.options.user_instruction,
                style=request.options.rewrite_style,
                focus=request.options.focus_point,
                length=request.options.length_mode,
                selection_mode=request.selection_mode,
                writing_policy_block=writing_policy.prompt_block,
            )
        finally:
            merge_provider_debug(trace_id, writing_policy.diagnostic_patch())
        rewritten_text = provider_result["rewrittenText"]
        writing_policy_audit = writing_policy_service.audit(
            writing_policy,
            source_text,
            rewritten_text,
        )
        return {
            "originalText": source_text,
            "rewrittenText": rewritten_text,
            "rewriteMode": action,
            "diffHints": self._build_diff_hints(source_text, rewritten_text),
            "provider": provider_result.get("provider", "mock"),
            "writingPolicyUsage": writing_policy.usage,
            "writingPolicyAudit": writing_policy_audit,
        }

    def _get_writing_policy_service(self) -> WritingPolicyService:
        if self.writing_policy_service is not None:
            return self.writing_policy_service
        return get_writing_policy_service()

    def _extract_source_text(self, request: WordDocumentRequest) -> str:
        source_text = request.content.plain_text.strip()
        if not source_text:
            source_text = "\n".join(
                paragraph.text for paragraph in request.content.paragraphs if paragraph.text.strip()
            ).strip()
        return source_text

    def _build_diff_hints(self, original_text: str, rewritten_text: str) -> List[str]:
        hints: List[str] = []
        if rewritten_text != original_text:
            hints.append("Text content changed")
        if len(rewritten_text) > len(original_text):
            hints.append("Expanded content length")
        if len(rewritten_text) < len(original_text):
            hints.append("Compressed content length")
        return hints
