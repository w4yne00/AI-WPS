import importlib.util
import os
import unittest
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

HAS_PYDANTIC = importlib.util.find_spec("pydantic") is not None

if HAS_PYDANTIC:
    from app.core.errors import AdapterError
    from app.core.models import WordDocumentRequest
    from app.services.enterprise_knowledge import KnowledgeMatchResult
    from app.services.enterprise_knowledge import service as knowledge_service_module
    from app.services.provider_client import get_last_provider_debug, record_provider_debug, reset_provider_debug
    from app.services.word import smart_imitator as smart_imitator_module
    from app.services.word.smart_imitator import WordSmartImitator


PROJECT_KNOWLEDGE_DB = Path(__file__).resolve().parents[2] / "run" / "enterprise_knowledge.db"
_MISSING_ENV = object()


def database_signature(path):
    try:
        stat_result = path.stat()
    except FileNotFoundError:
        return None
    return (stat_result.st_mtime_ns, stat_result.st_size)


@contextmanager
def isolated_default_knowledge_database(test_case):
    project_signature = database_signature(PROJECT_KNOWLEDGE_DB)
    previous = os.environ.get("AI_WPS_ENTERPRISE_KNOWLEDGE_DB", _MISSING_ENV)
    with TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "enterprise_knowledge.db"
        knowledge_service_module._reset_enterprise_knowledge_services()
        os.environ["AI_WPS_ENTERPRISE_KNOWLEDGE_DB"] = str(db_path)
        try:
            yield db_path
        finally:
            knowledge_service_module._reset_enterprise_knowledge_services()
            if previous is _MISSING_ENV:
                os.environ.pop("AI_WPS_ENTERPRISE_KNOWLEDGE_DB", None)
            else:
                os.environ["AI_WPS_ENTERPRISE_KNOWLEDGE_DB"] = previous
            test_case.assertEqual(
                database_signature(PROJECT_KNOWLEDGE_DB),
                project_signature,
            )


def parse_word_request(payload):
    if hasattr(WordDocumentRequest, "model_validate"):
        return WordDocumentRequest.model_validate(payload)
    return WordDocumentRequest.parse_obj(payload)


class RecordingSmartImitationProvider:
    def __init__(self):
        self.calls = []

    def smart_imitation(
        self,
        template_text,
        requirement,
        reference_material,
        trace_id,
        enterprise_knowledge_block,
    ):
        self.calls.append(
            {
                "templateText": template_text,
                "requirement": requirement,
                "referenceMaterial": reference_material,
                "traceId": trace_id,
                "enterpriseKnowledgeBlock": enterprise_knowledge_block,
            }
        )
        record_provider_debug(
            {
                "traceId": trace_id,
                "taskType": "word.smart_imitation",
                "stage": "response",
                "provider": "enterprise-dify-chat",
            }
        )
        return {
            "rewrittenText": "仿写后的技术风险提示。",
            "provider": "enterprise-dify-chat/task-file",
        }


class FakeKnowledgeService:
    def __init__(self, degraded=False):
        self.calls = []
        self.usage = {
            "applied": not degraded,
            "degraded": degraded,
            "degradedReason": "企业知识服务暂时不可用，已跳过企业知识增强。" if degraded else "",
            "termMatchCount": 0 if degraded else 1,
            "styleRuleCount": 0,
            "truncatedCount": 0,
            "matchedItems": [] if degraded else [{"id": "t1", "type": "term", "name": "标准术语"}],
        }
        self.result = KnowledgeMatchResult(
            "" if degraded else "企业术语与写作规范（必须遵守）：\n- 使用标准术语。",
            self.usage,
            () if degraded else ("t1",),
            {
                "knowledgeApplied": not degraded,
                "knowledgeDegraded": degraded,
                "knowledgeErrorCode": "knowledge_io_error" if degraded else "",
                "knowledgeTermCount": 0 if degraded else 1,
                "knowledgeStyleCount": 0,
                "knowledgeTruncatedCount": 0,
                "knowledgeElapsedMs": 2,
                "knowledgeItemIds": [] if degraded else ["t1"],
            },
        )

    def prepare(self, task_scope, source_parts):
        self.calls.append((task_scope, list(source_parts)))
        return self.result


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

    def test_smart_imitation_resolves_default_knowledge_only_when_task_runs(self):
        provider = RecordingSmartImitationProvider()
        knowledge = FakeKnowledgeService()

        with patch.object(
            smart_imitator_module,
            "get_enterprise_knowledge_service",
            return_value=knowledge,
        ) as getter:
            imitator = WordSmartImitator(provider)
            getter.assert_not_called()

            result = imitator.imitate(
                self._request(),
                "trace-smart-imitation-lazy-knowledge",
            )

        getter.assert_called_once_with()
        self.assertEqual(provider.calls[0]["enterpriseKnowledgeBlock"], knowledge.result.prompt_block)
        self.assertEqual(result["knowledgeUsage"], knowledge.result.usage)

    def test_smart_imitation_sends_template_requirement_and_reference(self):
        reset_provider_debug()
        provider = RecordingSmartImitationProvider()
        knowledge = FakeKnowledgeService()
        result = WordSmartImitator(provider_client=provider, knowledge_service=knowledge).imitate(
            self._request(),
            trace_id="trace-smart-imitation",
        )

        self.assertEqual(
            knowledge.calls,
            [
                (
                    "word.smart_imitation",
                    ["模板段落。", "仿写成技术风险提示。", "风险：接口超时。"],
                )
            ],
        )
        self.assertEqual(provider.calls[0]["templateText"], "模板段落。")
        self.assertEqual(provider.calls[0]["requirement"], "仿写成技术风险提示。")
        self.assertEqual(provider.calls[0]["referenceMaterial"], "风险：接口超时。")
        self.assertEqual(provider.calls[0]["enterpriseKnowledgeBlock"], knowledge.result.prompt_block)
        self.assertEqual(result["originalText"], "模板段落。")
        self.assertEqual(result["rewrittenText"], "仿写后的技术风险提示。")
        self.assertEqual(result["rewriteMode"], "imitate")
        self.assertEqual(result["diffHints"], [])
        self.assertEqual(result["provider"], "enterprise-dify-chat/task-file")
        self.assertEqual(result["knowledgeUsage"], knowledge.result.usage)
        debug = get_last_provider_debug()
        self.assertEqual(debug["stage"], "response")
        self.assertEqual(debug["provider"], "enterprise-dify-chat")
        self.assertTrue(debug["knowledgeApplied"])

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
        knowledge = FakeKnowledgeService()

        WordSmartImitator(provider_client=provider, knowledge_service=knowledge).imitate(
            request,
            trace_id="trace-paragraphs",
        )

        self.assertEqual(provider.calls[0]["templateText"], "第一段模板。\n第二段模板。")

    def test_smart_imitation_requires_template_and_requirement(self):
        imitator = WordSmartImitator(
            provider_client=RecordingSmartImitationProvider(),
            knowledge_service=FakeKnowledgeService(),
        )

        with self.assertRaises(AdapterError) as missing_template:
            imitator.imitate(self._request(template_text=""), trace_id="trace-missing-template")
        self.assertEqual(missing_template.exception.code, "SMART_IMITATION_TEMPLATE_REQUIRED")
        self.assertIn("仿写模板", missing_template.exception.message)

        with self.assertRaises(AdapterError) as missing_requirement:
            imitator.imitate(self._request(requirement=""), trace_id="trace-missing-requirement")
        self.assertEqual(missing_requirement.exception.code, "SMART_IMITATION_REQUIREMENT_REQUIRED")
        self.assertIn("仿写需求", missing_requirement.exception.message)

    def test_smart_imitation_degraded_knowledge_still_calls_provider(self):
        provider = RecordingSmartImitationProvider()
        knowledge = FakeKnowledgeService(degraded=True)

        result = WordSmartImitator(provider, knowledge_service=knowledge).imitate(
            self._request(),
            trace_id="trace-imitation-degraded",
        )

        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(provider.calls[0]["enterpriseKnowledgeBlock"], "")
        self.assertEqual(result["knowledgeUsage"], knowledge.result.usage)
        self.assertTrue(result["knowledgeUsage"]["degraded"])

    def test_smart_imitation_defaults_to_empty_enterprise_knowledge_service(self):
        provider = RecordingSmartImitationProvider()
        with isolated_default_knowledge_database(self) as db_path:
            imitator = WordSmartImitator(provider)
            self.assertFalse(db_path.exists())

            result = imitator.imitate(
                self._request(),
                trace_id="trace-imitation-default",
            )

            self.assertTrue(db_path.exists())
        self.assertEqual(provider.calls[0]["enterpriseKnowledgeBlock"], "")
        self.assertTrue(result["knowledgeUsage"]["applied"])
        self.assertFalse(result["knowledgeUsage"]["degraded"])
        self.assertEqual(result["knowledgeUsage"]["termMatchCount"], 0)
        self.assertEqual(result["knowledgeUsage"]["matchedItems"], [])


if __name__ == "__main__":
    unittest.main()
