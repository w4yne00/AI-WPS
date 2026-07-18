from typing import Dict, List, Optional

from app.core.models import WordDocumentRequest
from app.services.enterprise_knowledge import EnterpriseKnowledgeService, get_enterprise_knowledge_service
from app.services.provider_client import ProviderClient, merge_provider_debug


class WordRewriter:
    def __init__(
        self,
        provider_client: Optional[ProviderClient] = None,
        knowledge_service: Optional[EnterpriseKnowledgeService] = None,
    ) -> None:
        self.provider_client = provider_client or ProviderClient()
        self.knowledge_service = knowledge_service

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
        knowledge = self._get_knowledge_service().prepare(
            "word.smart_write",
            [source_text, request.options.user_instruction],
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
                enterprise_knowledge_block=knowledge.prompt_block,
            )
        finally:
            merge_provider_debug(trace_id, knowledge.diagnostic_patch())
        rewritten_text = provider_result["rewrittenText"]
        return {
            "originalText": source_text,
            "rewrittenText": rewritten_text,
            "rewriteMode": action,
            "diffHints": self._build_diff_hints(source_text, rewritten_text),
            "provider": provider_result.get("provider", "mock"),
            "knowledgeUsage": knowledge.usage,
        }

    def _get_knowledge_service(self) -> EnterpriseKnowledgeService:
        if self.knowledge_service is not None:
            return self.knowledge_service
        return get_enterprise_knowledge_service()

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
