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
    from app.services.writing_policy import WritingPolicyMatchResult, WritingPolicyService
    from app.services.writing_policy import service as writing_policy_service_module
    from app.services.writing_policy.store import WritingPolicyStore
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
    def __init__(self, result_text="仿写后的技术风险提示。"):
        self.calls = []
        self.result_text = result_text

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
            "rewrittenText": self.result_text,
            "provider": "enterprise-dify-chat/task-file",
        }


class FakeWritingPolicyService:
    def __init__(self, degraded=False):
        self.calls = []
        self.audit_calls = []
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

    def prepare(self, task_scope, source_parts, scene="auto"):
        self.calls.append((task_scope, list(source_parts), scene))
        return self.result

    def audit(self, _match_result, source_text, result_text):
        self.audit_calls.append((source_text, result_text))
        return {
            "enabled": True,
            "passed": True,
            "degraded": False,
            "degradedReason": "",
            "summary": "已完成写作规范检查",
            "needsReview": [],
            "expressionSuggestions": [],
        }


class EmptyWritingPolicyStore:
    def enabled_items(self, _task_scope, _scene_id=None):
        return [], []


class FailingAuditWritingPolicyService(FakeWritingPolicyService):
    def audit(self, _match_result, _source_text, _result_text):
        raise RuntimeError("audit unavailable")


@unittest.skipUnless(HAS_PYDANTIC, "pydantic is required for smart imitation tests")
class WordSmartImitationTests(unittest.TestCase):
    def _request(
        self,
        template_text="模板段落。",
        requirement="仿写成技术风险提示。",
        reference="风险：接口超时。",
        writing_policy_scene="auto",
    ):
        return parse_word_request(
            {
                "documentId": "imitate.docx",
                "scene": "word",
                "selectionMode": "selection",
                "writingPolicyScene": writing_policy_scene,
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
                    "auto",
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

    def test_smart_imitation_audits_protected_inputs_without_treating_template_facts_as_output(self):
        provider = RecordingSmartImitationProvider()
        writing_policy = WritingPolicyService(store=EmptyWritingPolicyStore())

        result = WordSmartImitator(
            provider_client=provider,
            writing_policy_service=writing_policy,
        ).imitate(
            self._request(
                template_text="示例部门负责在 2024年1月1日前完成 2 项模板任务。",
                requirement="保留两段结构，仿写成网络安全整改通知。",
                reference="信息化部门负责在 2026年7月25日前完成 3 项等保整改。",
                writing_policy_scene="cybersecurity",
            ),
            trace_id="trace-smart-imitation-scene-audit",
        )

        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(result["writingPolicyUsage"]["requestedScene"], "cybersecurity")
        self.assertEqual(result["writingPolicyUsage"]["scene"], "cybersecurity")
        self.assertEqual(
            result["writingPolicyUsage"]["packNames"],
            ["G企技术写作基础", "技术文件文体", "网络安全术语"],
        )
        self.assertTrue(result["writingPolicyAudit"]["enabled"])
        codes = {
            item["code"]
            for item in result["writingPolicyAudit"]["needsReview"]
        }
        self.assertIn("protected_date_changed", codes)
        self.assertIn("protected_number_changed", codes)
        self.assertIn("responsibility_subject_changed", codes)
        self.assertIn("standard_term_changed", codes)
        evidence = {
            item["evidence"]
            for item in result["writingPolicyAudit"]["needsReview"]
        }
        self.assertFalse(any("2024" in item for item in evidence))
        self.assertNotIn("2", evidence)
        self.assertEqual(result["rewrittenText"], "仿写后的技术风险提示。")

    def test_smart_imitation_audits_template_facts_explicitly_preserved_by_user(self):
        provider = RecordingSmartImitationProvider(
            "安全部负责在 2026年7月25日前完成 3 项整改。"
        )
        writing_policy = WritingPolicyService(store=EmptyWritingPolicyStore())

        result = WordSmartImitator(
            provider_client=provider,
            writing_policy_service=writing_policy,
        ).imitate(
            self._request(
                template_text="技术部负责在 2025年6月18日前完成 2 项检查。",
                requirement="请保留模板中的日期、数字和责任主体。",
                reference="",
                writing_policy_scene="yangqi",
            ),
            trace_id="trace-smart-imitation-preserved-template-facts",
        )

        codes = {
            item["code"]
            for item in result["writingPolicyAudit"]["needsReview"]
        }
        self.assertIn("protected_date_changed", codes)
        self.assertIn("protected_number_changed", codes)
        self.assertIn("responsibility_subject_changed", codes)
        self.assertEqual(len(provider.calls), 1)

    def test_smart_imitation_does_not_treat_preserved_template_structure_as_preserved_facts(self):
        provider = RecordingSmartImitationProvider(
            "安全部负责在 2026年7月25日前完成 3 项整改。"
        )
        writing_policy = WritingPolicyService(store=EmptyWritingPolicyStore())

        result = WordSmartImitator(
            provider_client=provider,
            writing_policy_service=writing_policy,
        ).imitate(
            self._request(
                template_text="技术部负责在 2025年6月18日前完成 2 项检查。",
                requirement="请保持模板内容的段落结构。",
                reference="",
                writing_policy_scene="yangqi",
            ),
            trace_id="trace-smart-imitation-preserved-structure-not-facts",
        )

        protected_codes = {
            "protected_date_changed",
            "protected_number_changed",
            "responsibility_subject_changed",
        }
        codes = {
            item["code"]
            for item in result["writingPolicyAudit"]["needsReview"]
        }
        self.assertFalse(codes & protected_codes)

    def test_smart_imitation_treats_unqualified_preserved_template_content_as_preserved_facts(self):
        provider = RecordingSmartImitationProvider(
            "安全部负责在 2026年7月25日前完成 3 项整改。"
        )
        writing_policy = WritingPolicyService(store=EmptyWritingPolicyStore())

        result = WordSmartImitator(
            provider_client=provider,
            writing_policy_service=writing_policy,
        ).imitate(
            self._request(
                template_text="技术部负责在 2025年6月18日前完成 2 项检查。",
                requirement="请保留模板内容，仅调整表达。",
                reference="",
                writing_policy_scene="yangqi",
            ),
            trace_id="trace-smart-imitation-preserved-template-content",
        )

        codes = {
            item["code"]
            for item in result["writingPolicyAudit"]["needsReview"]
        }
        self.assertIn("protected_date_changed", codes)
        self.assertIn("protected_number_changed", codes)
        self.assertIn("responsibility_subject_changed", codes)

    def test_smart_imitation_does_not_attach_later_style_instruction_to_template_content(self):
        provider = RecordingSmartImitationProvider(
            "安全部负责在 2026年7月25日前完成 3 项整改。"
        )
        writing_policy = WritingPolicyService(store=EmptyWritingPolicyStore())

        result = WordSmartImitator(
            provider_client=provider,
            writing_policy_service=writing_policy,
        ).imitate(
            self._request(
                template_text="技术部负责在 2025年6月18日前完成 2 项检查。",
                requirement="请保留模板内容并调整表达风格。",
                reference="",
                writing_policy_scene="yangqi",
            ),
            trace_id="trace-smart-imitation-content-and-style",
        )

        codes = {
            item["code"]
            for item in result["writingPolicyAudit"]["needsReview"]
        }
        self.assertIn("protected_date_changed", codes)
        self.assertIn("protected_number_changed", codes)
        self.assertIn("responsibility_subject_changed", codes)

    def test_smart_imitation_keeps_model_result_when_result_check_fails(self):
        provider = RecordingSmartImitationProvider()

        result = WordSmartImitator(
            provider_client=provider,
            writing_policy_service=FailingAuditWritingPolicyService(),
        ).imitate(
            self._request(),
            trace_id="trace-smart-imitation-audit-degraded",
        )

        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(result["rewrittenText"], "仿写后的技术风险提示。")
        self.assertTrue(result["writingPolicyAudit"]["enabled"])
        self.assertTrue(result["writingPolicyAudit"]["degraded"])
        self.assertIn("仍可正常预览、复制", result["writingPolicyAudit"]["summary"])
        self.assertEqual(result["writingPolicyAudit"]["needsReview"], [])
        self.assertEqual(result["writingPolicyAudit"]["expressionSuggestions"], [])

    def test_smart_imitation_does_not_suggest_removing_explicitly_preserved_template_structure(self):
        provider = RecordingSmartImitationProvider(
            "首先核对账号，其次检查日志，再次修复漏洞，最后复核结果。"
        )
        writing_policy = WritingPolicyService(store=EmptyWritingPolicyStore())

        result = WordSmartImitator(
            provider_client=provider,
            writing_policy_service=writing_policy,
        ).imitate(
            self._request(
                template_text="首先核对范围，其次分析原因，再次落实措施，最后形成结论。",
                requirement="请保留模板中的首先、其次、再次、最后。",
                reference="",
                writing_policy_scene="yangqi",
            ),
            trace_id="trace-smart-imitation-preserved-structure",
        )

        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(
            result["writingPolicyAudit"]["expressionSuggestions"],
            [],
        )
        self.assertTrue(result["writingPolicyAudit"]["passed"])

    def test_smart_imitation_keeps_unrelated_expression_suggestions(self):
        provider = RecordingSmartImitationProvider(
            "首先核对账号，其次检查日志，再次修复漏洞，最后复核结果。"
        )
        writing_policy = WritingPolicyService(store=EmptyWritingPolicyStore())

        result = WordSmartImitator(
            provider_client=provider,
            writing_policy_service=writing_policy,
        ).imitate(
            self._request(
                template_text="首先核对范围，其次分析原因，再次落实措施，最后形成结论。",
                requirement="请保持模板标题不变。",
                reference="",
                writing_policy_scene="yangqi",
            ),
            trace_id="trace-smart-imitation-unrelated-suggestion",
        )

        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(
            {
                item["code"]
                for item in result["writingPolicyAudit"]["expressionSuggestions"]
            },
            {"template_expression_t3"},
        )
        self.assertFalse(result["writingPolicyAudit"]["passed"])

    def test_smart_imitation_does_not_treat_negative_preservation_as_preserved_structure(self):
        provider = RecordingSmartImitationProvider(
            "首先核对账号，其次检查日志，再次修复漏洞，最后复核结果。"
        )
        writing_policy = WritingPolicyService(store=EmptyWritingPolicyStore())

        result = WordSmartImitator(
            provider_client=provider,
            writing_policy_service=writing_policy,
        ).imitate(
            self._request(
                template_text="首先核对范围，其次分析原因，再次落实措施，最后形成结论。",
                requirement="不要保留模板中的首先、其次、再次、最后。",
                reference="",
                writing_policy_scene="yangqi",
            ),
            trace_id="trace-smart-imitation-negative-preservation",
        )

        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(
            {
                item["code"]
                for item in result["writingPolicyAudit"]["expressionSuggestions"]
            },
            {"template_expression_t3"},
        )
        self.assertFalse(result["writingPolicyAudit"]["passed"])

    def test_smart_imitation_does_not_mix_preservation_targets_across_clauses(self):
        provider = RecordingSmartImitationProvider(
            "首先核对账号，其次检查日志，再次修复漏洞，最后复核结果。"
        )
        writing_policy = WritingPolicyService(store=EmptyWritingPolicyStore())

        result = WordSmartImitator(
            provider_client=provider,
            writing_policy_service=writing_policy,
        ).imitate(
            self._request(
                template_text="首先核对范围，其次分析原因，再次落实措施，最后形成结论。",
                requirement="不要保留模板结构，但请保持模板标题不变。",
                reference="",
                writing_policy_scene="yangqi",
            ),
            trace_id="trace-smart-imitation-preservation-clauses",
        )

        self.assertEqual(
            {
                item["code"]
                for item in result["writingPolicyAudit"]["expressionSuggestions"]
            },
            {"template_expression_t3"},
        )
        self.assertFalse(result["writingPolicyAudit"]["passed"])

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

    def test_smart_imitation_defaults_to_bundled_writing_policy_scene(self):
        provider = RecordingSmartImitationProvider()
        with isolated_default_writing_policy_database(self) as db_path:
            imitator = WordSmartImitator(provider)
            self.assertFalse(db_path.exists())

            result = imitator.imitate(
                self._request(),
                trace_id="trace-imitation-default",
            )

            self.assertTrue(db_path.exists())
        self.assertIn(
            "仿写模板的结构与句式意图",
            provider.calls[0]["writingPolicyBlock"],
        )
        self.assertTrue(result["writingPolicyUsage"]["applied"])
        self.assertFalse(result["writingPolicyUsage"]["degraded"])
        self.assertEqual(result["writingPolicyUsage"]["termMatchCount"], 0)
        self.assertGreater(result["writingPolicyUsage"]["styleRuleCount"], 0)
        self.assertEqual(
            result["writingPolicyUsage"]["packNames"],
            ["G企技术写作基础"],
        )

    def test_smart_imitation_applies_scoped_organization_style_rule_once(self):
        provider = RecordingSmartImitationProvider()
        with isolated_default_writing_policy_database(self) as db_path:
            store = WritingPolicyStore(db_path)
            store.create_item(
                {
                    "type": "style",
                    "name": "仿写保留动作链",
                    "ruleText": "仿写结果应明确责任主体、动作和完成条件。",
                    "positiveExample": "运维部门完成核验后提交记录。",
                    "negativeExample": "相关工作后续持续推进。",
                    "contextKeywords": [],
                    "alwaysApply": True,
                    "priority": "high",
                    "taskTypes": ["word.smart_imitation"],
                    "sceneIds": ["cybersecurity"],
                    "enabled": True,
                    "note": "组织规则端到端测试",
                }
            )
            for name, rule_text, task_types, scene_ids in (
                (
                    "审查专用排除规则",
                    "此规则只允许进入文档审查。",
                    ["word.document_review"],
                    ["cybersecurity"],
                ),
                (
                    "党政公文场景排除规则",
                    "此规则只允许进入党政公文场景。",
                    ["word.smart_imitation"],
                    ["official"],
                ),
            ):
                store.create_item(
                    {
                        "type": "anti_template",
                        "name": name,
                        "ruleText": rule_text,
                        "contextKeywords": [],
                        "alwaysApply": True,
                        "priority": "high",
                        "taskTypes": task_types,
                        "sceneIds": scene_ids,
                        "enabled": True,
                    }
                )

            result = WordSmartImitator(provider).imitate(
                self._request(writing_policy_scene="cybersecurity"),
                trace_id="trace-smart-imitation-scoped-rule",
            )

        self.assertEqual(len(provider.calls), 1)
        self.assertIn(
            "仿写结果应明确责任主体、动作和完成条件",
            provider.calls[0]["writingPolicyBlock"],
        )
        self.assertNotIn(
            "此规则只允许进入文档审查",
            provider.calls[0]["writingPolicyBlock"],
        )
        self.assertNotIn(
            "此规则只允许进入党政公文场景",
            provider.calls[0]["writingPolicyBlock"],
        )
        self.assertGreaterEqual(result["writingPolicyUsage"]["styleRuleCount"], 1)


if __name__ == "__main__":
    unittest.main()
