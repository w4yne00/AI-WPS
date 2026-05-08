from typing import Dict, Optional

from app.core.models import WordDocumentRequest
from app.services.provider_client import (
    ProviderClient,
    get_default_technical_review_prompt,
)


class WordTechnicalReviewer:
    def __init__(self, provider_client: Optional[ProviderClient] = None) -> None:
        self.provider_client = provider_client or ProviderClient()

    def review(self, request: WordDocumentRequest, trace_id: str) -> Dict:
        source_text = request.content.plain_text.strip()
        if not source_text:
            source_text = "\n".join(
                paragraph.text for paragraph in request.content.paragraphs if paragraph.text.strip()
            ).strip()

        review_prompt = request.options.technical_review_prompt.strip()
        if not review_prompt:
            review_prompt = get_default_technical_review_prompt()

        provider_result = self.provider_client.technical_review(
            source_text,
            trace_id,
            document_type=request.options.technical_document_type,
            review_prompt=review_prompt,
        )
        return {
            "documentType": request.options.technical_document_type,
            "reviewPrompt": review_prompt,
            "summary": provider_result.get("summary", ""),
            "issues": provider_result.get("issues", []),
            "provider": provider_result.get("provider", "mock"),
        }
