from typing import Dict, List, Optional

from app.core.models import WordDocumentRequest
from app.services.dify_client import DifyClient


class WordRewriter:
    def __init__(self, dify_client: Optional[DifyClient] = None) -> None:
        self.dify_client = dify_client or DifyClient()

    def rewrite(self, request: WordDocumentRequest, trace_id: str, mode: str = "rewrite") -> Dict:
        source_text = request.content.plain_text.strip()
        if not source_text:
            source_text = "\n".join(
                paragraph.text for paragraph in request.content.paragraphs if paragraph.text.strip()
            ).strip()

        dify_result = self.dify_client.rewrite(source_text, mode, trace_id)
        rewritten_text = dify_result["rewrittenText"]
        return {
            "originalText": source_text,
            "rewrittenText": rewritten_text,
            "rewriteMode": mode,
            "diffHints": self._build_diff_hints(source_text, rewritten_text),
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
