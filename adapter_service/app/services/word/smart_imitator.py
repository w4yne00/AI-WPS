from typing import Dict, Optional

from app.core.errors import AdapterError
from app.core.models import WordDocumentRequest
from app.services.writing_policy import WritingPolicyService, get_writing_policy_service
from app.services.provider_client import ProviderClient, merge_provider_debug


class WordSmartImitator:
    def __init__(
        self,
        provider_client: Optional[ProviderClient] = None,
        writing_policy_service: Optional[WritingPolicyService] = None,
    ) -> None:
        self.provider_client = provider_client or ProviderClient()
        self.writing_policy_service = writing_policy_service

    def imitate(self, request: WordDocumentRequest, trace_id: str) -> Dict:
        template_text = self._extract_template_text(request)
        requirement = request.options.imitation_requirement.strip()
        reference_material = request.options.imitation_reference_material.strip()

        if not template_text:
            raise AdapterError("SMART_IMITATION_TEMPLATE_REQUIRED", "请先提供仿写模板。", status_code=400)
        if not requirement:
            raise AdapterError("SMART_IMITATION_REQUIREMENT_REQUIRED", "请填写仿写需求。", status_code=400)

        writing_policy = self._get_writing_policy_service().prepare(
            "word.smart_imitation",
            [template_text, requirement, reference_material],
        )
        try:
            provider_result = self.provider_client.smart_imitation(
                template_text,
                requirement,
                reference_material,
                trace_id,
                writing_policy_block=writing_policy.prompt_block,
            )
        finally:
            merge_provider_debug(trace_id, writing_policy.diagnostic_patch())
        return {
            "originalText": template_text,
            "rewrittenText": provider_result["rewrittenText"],
            "rewriteMode": "imitate",
            "diffHints": [],
            "provider": provider_result.get("provider", "mock"),
            "writingPolicyUsage": writing_policy.usage,
            "writingPolicyAudit": {
                "needsReview": [],
                "expressionSuggestions": [],
            },
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
