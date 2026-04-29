from typing import Dict, List, Optional

from app.core.models import WordDocumentRequest
from app.services.provider_client import ProviderClient


class WordRewriter:
    def __init__(self, provider_client: Optional[ProviderClient] = None) -> None:
        self.provider_client = provider_client or ProviderClient()

    def rewrite(self, request: WordDocumentRequest, trace_id: str, mode: str = "rewrite") -> Dict:
        source_text = request.content.plain_text.strip()
        if not source_text:
            source_text = "\n".join(
                paragraph.text for paragraph in request.content.paragraphs if paragraph.text.strip()
            ).strip()

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

    def _build_diff_hints(self, original_text: str, rewritten_text: str) -> List[str]:
        hints: List[str] = []
        if rewritten_text != original_text:
            hints.append("Text content changed")
        if len(rewritten_text) > len(original_text):
            hints.append("Expanded content length")
        if len(rewritten_text) < len(original_text):
            hints.append("Compressed content length")
        return hints
