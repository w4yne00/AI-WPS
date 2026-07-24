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
    from app.services.writing_policy import WritingPolicyMatchResult
    from app.services.writing_policy import service as writing_policy_service_module
    from app.services.provider_client import get_last_provider_debug, record_provider_debug, reset_provider_debug
    from app.services.word import smart_imitator as smart_imitator_module
    from app.services.word.smart_imitator import WordSmartImitator


PROJECT_WRITING_POLICY_DB = Path(__file__).resolve().parents[2] / "run" / "writing_policies.db"
_MISSING_ENV = object()


def database_signature(path):
    try:
        stat_result = path.stat()
    except FileNotFoundError:
        return None
    return (stat_result.st_mtime_ns, stat_result.st_size)


@contextmanager
def isolated_default_writing_policy_database(test_case):
    project_signature = database_signature(PROJECT_WRITING_POLICY_DB)
    previous = os.environ.get("AI_WPS_WRITING_POLICY_DB", _MISSING_ENV)
    with TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "writing_policies.db"
        writing_policy_service_module._reset_writing_policy_services()
        os.environ["AI_WPS_WRITING_POLICY_DB"] = str(db_path)
        try:
            yield db_path
        finally:
            writing_policy_service_module._reset_writing_policy_services()
            if previous is _MISSING_ENV:
                os.environ.pop("AI_WPS_WRITING_POLICY_DB", None)
            else:
                os.environ["AI_WPS_WRITING_POLICY_DB"] = previous
            test_case.assertEqual(
                database_signature(PROJECT_WRITING_POLICY_DB),
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
        writing_policy_block,
    ):
        self.calls.append(
            {
                "templateText": template_text,
                "requirement": requirement,
                "referenceMaterial": reference_material,
                "traceId": trace_id,
                "writingPolicyBlock": writing_policy_block,
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


class FakeWritingPolicyService:
    def __init__(self, degraded=False):
        self.calls = []
        self.usage = {
            "applied": not degraded,
            "degraded": degraded,
            "degradedReason": "写作规范服务暂时不可用，已跳过写作规范增强。" if degraded else "",
            "termMatchCount": 0 if degraded else 1,
            "styleRuleCount": 0,
            "truncatedCount": 0,
            "matchedItems": [] if degraded else [{"id": "t1", "type": "term", "name": "标准术语"}],
        }
        self.result = WritingPolicyMatchResult(
            "" if degraded else "写作规范（必须遵守）：\n- 使用标准术语。",
            self.usage,
            () if degraded else ("t1",),
            {
                "writingPolicyApplied": not degraded,
                "writingPolicyDegraded": degraded,
                "writingPolicyErrorCode": "writing_policy_io_error" if degraded else "",
                "writingPolicyTermCount": 0 if degraded else 1,
                "writingPolicyStyleCount": 0,
                "writingPolicyTruncatedCount": 0,
                "writingPolicyElapsedMs": 2,
                "writingPolicyItemIds": [] if degraded else ["t1"],
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

    def test_smart_imitation_resolves_default_writing_policy_only_when_task_runs(self):
        provider = RecordingSmartImitationProvider()
        writing_policy = FakeWritingPolicyService()

        with patch.object(
            smart_imitator_module,
            "get_writing_policy_service",
            return_value=writing_policy,
        ) as getter:
            imitator = WordSmartImitator(provider)
            getter.assert_not_called()

            result = imitator.imitate(
                self._request(),
                "trace-smart-imitation-lazy-writing_policy",
            )

        getter.assert_called_once_with()
        self.assertEqual(provider.calls[0]["writingPolicyBlock"], writing_policy.result.prompt_block)
        self.assertEqual(result["writingPolicyUsage"], writing_policy.result.usage)

    def test_smart_imitation_sends_template_requirement_and_reference(self):
        reset_provider_debug()
        provider = RecordingSmartImitationProvider()
        writing_policy = FakeWritingPolicyService()
        result = WordSmartImitator(provider_client=provider, writing_policy_service=writing_policy).imitate(
            self._request(),
            trace_id="trace-smart-imitation",
        )

        self.assertEqual(
            writing_policy.calls,
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
        self.assertEqual(provider.calls[0]["writingPolicyBlock"], writing_policy.result.prompt_block)
        self.assertEqual(result["originalText"], "模板段落。")
        self.assertEqual(result["rewrittenText"], "仿写后的技术风险提示。")
        self.assertEqual(result["rewriteMode"], "imitate")
        self.assertEqual(result["diffHints"], [])
        self.assertEqual(result["provider"], "enterprise-dify-chat/task-file")
        self.assertEqual(result["writingPolicyUsage"], writing_policy.result.usage)
        debug = get_last_provider_debug()
        self.assertEqual(debug["stage"], "response")
        self.assertEqual(debug["provider"], "enterprise-dify-chat")
        self.assertTrue(debug["writingPolicyApplied"])

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
        writing_policy = FakeWritingPolicyService()

        WordSmartImitator(provider_client=provider, writing_policy_service=writing_policy).imitate(
            request,
            trace_id="trace-paragraphs",
        )

        self.assertEqual(provider.calls[0]["templateText"], "第一段模板。\n第二段模板。")

    def test_smart_imitation_requires_template_and_requirement(self):
        imitator = WordSmartImitator(
            provider_client=RecordingSmartImitationProvider(),
            writing_policy_service=FakeWritingPolicyService(),
        )

        with self.assertRaises(AdapterError) as missing_template:
            imitator.imitate(self._request(template_text=""), trace_id="trace-missing-template")
        self.assertEqual(missing_template.exception.code, "SMART_IMITATION_TEMPLATE_REQUIRED")
        self.assertIn("仿写模板", missing_template.exception.message)

        with self.assertRaises(AdapterError) as missing_requirement:
            imitator.imitate(self._request(requirement=""), trace_id="trace-missing-requirement")
        self.assertEqual(missing_requirement.exception.code, "SMART_IMITATION_REQUIREMENT_REQUIRED")
        self.assertIn("仿写需求", missing_requirement.exception.message)

    def test_smart_imitation_degraded_writing_policy_still_calls_provider(self):
        provider = RecordingSmartImitationProvider()
        writing_policy = FakeWritingPolicyService(degraded=True)

        result = WordSmartImitator(provider, writing_policy_service=writing_policy).imitate(
            self._request(),
            trace_id="trace-imitation-degraded",
        )

        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(provider.calls[0]["writingPolicyBlock"], "")
        self.assertEqual(result["writingPolicyUsage"], writing_policy.result.usage)
        self.assertTrue(result["writingPolicyUsage"]["degraded"])

    def test_smart_imitation_defaults_to_empty_writing_policy_service(self):
        provider = RecordingSmartImitationProvider()
        with isolated_default_writing_policy_database(self) as db_path:
            imitator = WordSmartImitator(provider)
            self.assertFalse(db_path.exists())

            result = imitator.imitate(
                self._request(),
                trace_id="trace-imitation-default",
            )

            self.assertTrue(db_path.exists())
        self.assertEqual(provider.calls[0]["writingPolicyBlock"], "")
        self.assertTrue(result["writingPolicyUsage"]["applied"])
        self.assertFalse(result["writingPolicyUsage"]["degraded"])
        self.assertEqual(result["writingPolicyUsage"]["termMatchCount"], 0)
        self.assertEqual(result["writingPolicyUsage"]["matchedItems"], [])


if __name__ == "__main__":
    unittest.main()
