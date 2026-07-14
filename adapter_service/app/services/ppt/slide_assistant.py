import re
from typing import Dict, Optional

from app.core.errors import AdapterError
from app.core.models import PptSlideAssistantRequest
from app.services.ppt.document_files import PptDocumentFileStore
from app.services.provider_client import ProviderClient


PPT_MAX_TITLE_LENGTH = 200
PPT_MAX_SUBTITLE_LENGTH = 300
PPT_MAX_BLOCK_LENGTH = 1000
PPT_MAX_BODY_LENGTH = 3000
PPT_MAX_ADJACENT_TITLE_LENGTH = 200
PPT_MAX_USER_INSTRUCTION_LENGTH = 1000
PPT_OPTIMIZE_MIN_BODY_CHARS = 20


def normalize_ppt_slide_request(request: PptSlideAssistantRequest) -> Dict:
    slide = request.slide
    if slide is None:
        raise AdapterError(
            "PPT_SLIDE_REQUIRED",
            "未读取到当前幻灯片，请确认 WPS 演示中已打开并选中一页幻灯片。",
            status_code=400,
        )

    original_title = slide.title or ""
    original_subtitle = slide.subtitle or ""
    original_previous_title = slide.previous_title or ""
    original_next_title = slide.next_title or ""
    original_instruction = request.user_instruction or ""
    title = original_title[:PPT_MAX_TITLE_LENGTH]
    subtitle = original_subtitle[:PPT_MAX_SUBTITLE_LENGTH]
    remaining_body = max(PPT_MAX_BODY_LENGTH - len(subtitle), 0)
    text_blocks = []
    truncated = bool(slide.truncated)

    if len(title) < len(original_title) or len(subtitle) < len(original_subtitle):
        truncated = True

    for source_block in slide.text_blocks:
        block = (source_block or "")[:PPT_MAX_BLOCK_LENGTH]
        if len(block) < len(source_block or ""):
            truncated = True
        if not block:
            continue
        if remaining_body <= 0:
            truncated = True
            break
        accepted = block[:remaining_body]
        if len(accepted) < len(block):
            truncated = True
        text_blocks.append(accepted)
        remaining_body -= len(accepted)
        if len(accepted) < len(block):
            break

    previous_title = original_previous_title[:PPT_MAX_ADJACENT_TITLE_LENGTH]
    next_title = original_next_title[:PPT_MAX_ADJACENT_TITLE_LENGTH]
    user_instruction = original_instruction[:PPT_MAX_USER_INSTRUCTION_LENGTH]
    if (
        len(previous_title) < len(original_previous_title)
        or len(next_title) < len(original_next_title)
        or len(user_instruction) < len(original_instruction)
    ):
        truncated = True

    return {
        "index": slide.index,
        "title": title,
        "subtitle": subtitle,
        "textBlocks": text_blocks,
        "previousTitle": previous_title,
        "nextTitle": next_title,
        "truncated": truncated,
        "userInstruction": user_instruction,
    }


def determine_ppt_slide_mode(context: Dict) -> str:
    blocks = context.get("textBlocks") or []
    body = "".join(str(block or "") for block in blocks)
    non_whitespace_count = len(re.sub(r"\s+", "", body))
    return "optimize" if non_whitespace_count >= PPT_OPTIMIZE_MIN_BODY_CHARS else "generate"


class PptSlideAssistant:
    def __init__(
        self,
        provider_client: Optional[ProviderClient] = None,
        document_file_store: Optional[PptDocumentFileStore] = None,
    ) -> None:
        self.provider_client = provider_client or ProviderClient()
        self.document_file_store = document_file_store or PptDocumentFileStore()

    def assist(self, request: PptSlideAssistantRequest, trace_id: str, progress_callback=None) -> Dict:
        if request.source_mode == "document":
            return self._assist_document(request, trace_id, progress_callback)
        return self._assist_slide(request, trace_id)

    def _assist_document(
        self,
        request: PptSlideAssistantRequest,
        trace_id: str,
        progress_callback=None,
    ) -> Dict:
        if not request.file_token.strip():
            raise AdapterError(
                "PPT_DOCUMENT_FILE_REQUIRED",
                "请先选择并上传 Markdown 或 Word 文档。",
                status_code=400,
            )
        staged = self.document_file_store.consume(request.file_token)
        try:
            if progress_callback:
                progress_callback("正在上传文档到模型后台。")
            return self.provider_client.ppt_document_summary(
                staged,
                request.requested_slide_count,
                (request.user_instruction or "")[:PPT_MAX_USER_INSTRUCTION_LENGTH],
                trace_id,
                progress_callback=progress_callback,
            )
        finally:
            self.document_file_store.delete(staged)

    def _assist_slide(self, request: PptSlideAssistantRequest, trace_id: str) -> Dict:
        context = normalize_ppt_slide_request(request)
        mode = determine_ppt_slide_mode(context)
        user_instruction = context.pop("userInstruction")
        if mode == "generate" and not user_instruction.strip():
            raise AdapterError(
                "PPT_SLIDE_INSTRUCTION_REQUIRED",
                "当前页正文内容不足，请填写本页主题或补充要求后再生成。",
                status_code=400,
            )

        provider_result = self.provider_client.ppt_slide_assistant(
            context,
            user_instruction,
            mode,
            trace_id,
        )
        return {
            "resultType": "slide",
            "modeUsed": mode,
            "suggestedTitle": provider_result.get("suggestedTitle", ""),
            "bullets": provider_result.get("bullets", []),
            "conclusion": provider_result.get("conclusion", ""),
            "plainText": provider_result.get("plainText", ""),
            "rawAnswer": provider_result.get("rawAnswer"),
            "parseFallbackReason": provider_result.get("parseFallbackReason"),
            "provider": provider_result.get("provider", "mock"),
        }
