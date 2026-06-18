from typing import Dict, Optional

from app.core.errors import AdapterError, ProviderTimeoutError
from app.core.models import WordDocumentRequest
from app.services.provider_client import (
    ProviderClient,
    get_default_document_review_prompt,
)


class WordDocumentReviewer:
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
            review_prompt = get_default_document_review_prompt(request.options.technical_document_type)

        try:
            provider_result = self.provider_client.document_review(
                source_text,
                trace_id,
                document_type=request.options.technical_document_type,
                review_prompt=review_prompt,
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
        return {
            "documentType": request.options.technical_document_type,
            "reviewPrompt": review_prompt,
            "scope": request.selection_mode,
            "summary": provider_result.get("summary", ""),
            "issues": provider_result.get("issues", []),
            "rawAnswer": provider_result.get("rawAnswer", ""),
            "parseFallbackReason": provider_result.get("parseFallbackReason", ""),
            "provider": provider_result.get("provider", "mock"),
        }

    def _provider_fallback(self, summary: str, detail: str, reason: str, provider: str) -> Dict:
        return {
            "summary": summary,
            "issues": [],
            "rawAnswer": detail,
            "parseFallbackReason": reason,
            "provider": provider,
        }
