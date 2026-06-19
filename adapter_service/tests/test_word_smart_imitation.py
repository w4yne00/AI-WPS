import importlib.util
import unittest

HAS_PYDANTIC = importlib.util.find_spec("pydantic") is not None

if HAS_PYDANTIC:
    from app.core.errors import AdapterError
    from app.core.models import WordDocumentRequest
    from app.services.word.smart_imitator import WordSmartImitator


def parse_word_request(payload):
    if hasattr(WordDocumentRequest, "model_validate"):
        return WordDocumentRequest.model_validate(payload)
    return WordDocumentRequest.parse_obj(payload)


class RecordingSmartImitationProvider:
    def __init__(self):
        self.calls = []

    def smart_imitation(self, template_text, requirement, reference_material, trace_id):
        self.calls.append(
            {
                "templateText": template_text,
                "requirement": requirement,
                "referenceMaterial": reference_material,
                "traceId": trace_id,
            }
        )
        return {
            "rewrittenText": "仿写后的技术风险提示。",
            "provider": "enterprise-dify-chat/task-file",
        }


@unittest.skipUnless(HAS_PYDANTIC, "pydantic is required for smart imitation tests")
class WordSmartImitationTests(unittest.TestCase):
    def _request(self, template_text="模板段落。", requirement="仿写成技术风险提示。", reference="风险：接口超时。"):
        return parse_word_request(
            {
                "documentId": "imitate.docx",
                "scene": "word",
                "selectionMode": "selection",
                "content": {
                    "plainText": template_text,
                    "paragraphs": [],
                    "headings": [],
                },
                "options": {
                    "imitationRequirement": requirement,
                    "imitationReferenceMaterial": reference,
                },
            }
        )

    def test_smart_imitation_sends_template_requirement_and_reference(self):
        provider = RecordingSmartImitationProvider()
        result = WordSmartImitator(provider_client=provider).imitate(
            self._request(),
            trace_id="trace-smart-imitation",
        )

        self.assertEqual(provider.calls[0]["templateText"], "模板段落。")
        self.assertEqual(provider.calls[0]["requirement"], "仿写成技术风险提示。")
        self.assertEqual(provider.calls[0]["referenceMaterial"], "风险：接口超时。")
        self.assertEqual(result["originalText"], "模板段落。")
        self.assertEqual(result["rewrittenText"], "仿写后的技术风险提示。")
        self.assertEqual(result["rewriteMode"], "imitate")
        self.assertEqual(result["diffHints"], [])
        self.assertEqual(result["provider"], "enterprise-dify-chat/task-file")

    def test_smart_imitation_falls_back_to_paragraph_text_for_template(self):
        request = parse_word_request(
            {
                "documentId": "imitate-paragraphs.docx",
                "scene": "word",
                "selectionMode": "document",
                "content": {
                    "plainText": "",
                    "paragraphs": [
                        {"index": 1, "text": "第一段模板。"},
                        {"index": 2, "text": "第二段模板。"},
                    ],
                    "headings": [],
                },
                "options": {
                    "imitationRequirement": "仿写成验收结论。",
                    "imitationReferenceMaterial": "",
                },
            }
        )
        provider = RecordingSmartImitationProvider()

        WordSmartImitator(provider_client=provider).imitate(request, trace_id="trace-paragraphs")

        self.assertEqual(provider.calls[0]["templateText"], "第一段模板。\n第二段模板。")

    def test_smart_imitation_requires_template_and_requirement(self):
        imitator = WordSmartImitator(provider_client=RecordingSmartImitationProvider())

        with self.assertRaises(AdapterError) as missing_template:
            imitator.imitate(self._request(template_text=""), trace_id="trace-missing-template")
        self.assertEqual(missing_template.exception.code, "SMART_IMITATION_TEMPLATE_REQUIRED")
        self.assertIn("仿写模板", missing_template.exception.message)

        with self.assertRaises(AdapterError) as missing_requirement:
            imitator.imitate(self._request(requirement=""), trace_id="trace-missing-requirement")
        self.assertEqual(missing_requirement.exception.code, "SMART_IMITATION_REQUIREMENT_REQUIRED")
        self.assertIn("仿写需求", missing_requirement.exception.message)


if __name__ == "__main__":
    unittest.main()
