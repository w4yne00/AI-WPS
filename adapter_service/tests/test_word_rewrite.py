import importlib.util
import os
import subprocess
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

HAS_API_DEPS = importlib.util.find_spec("fastapi") is not None and importlib.util.find_spec("pydantic") is not None
HAS_PYDANTIC = importlib.util.find_spec("pydantic") is not None

if HAS_PYDANTIC:
    from app.core.config import AppSettings
    from app.core.errors import ProviderUnavailableError
    from app.core.models import WordDocumentRequest
    from app.services.writing_policy import WritingPolicyMatchResult
    from app.services.writing_policy import service as writing_policy_service_module
    from app.services.writing_policy.store import WritingPolicyStore
    from app.services.provider_client import (
        ProviderClient,
        get_last_provider_debug,
        record_provider_debug,
        reset_provider_debug,
    )
    from app.services.word import rewriter as rewriter_module
    from app.services.word.rewriter import WordRewriter


PROJECT_WRITING_POLICY_DB = Path(__file__).resolve().parents[2] / "run" / "writing_policies.db"
_MISSING_ENV = object()


def database_signature(path):
    try:
        stat_result = path.stat()
    except FileNotFoundError:
        return None
    return (stat_result.st_mtime_ns, stat_result.st_size)


def restore_database_env(previous):
    if previous is _MISSING_ENV:
        os.environ.pop("AI_WPS_WRITING_POLICY_DB", None)
    else:
        os.environ["AI_WPS_WRITING_POLICY_DB"] = previous


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
            restore_database_env(previous)
            test_case.assertEqual(
                database_signature(PROJECT_WRITING_POLICY_DB),
                project_signature,
            )


if HAS_API_DEPS:
    from fastapi.testclient import TestClient

    from app.main import app


def parse_word_request(payload):
    if hasattr(WordDocumentRequest, "model_validate"):
        return WordDocumentRequest.model_validate(payload)
    return WordDocumentRequest.parse_obj(payload)


class FakeWritingPolicyService:
    def __init__(self, prompt_block="写作规范（必须遵守）：\n- 使用标准术语。", degraded=False):
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
            "" if degraded else prompt_block,
            self.usage,
            () if degraded else ("t1",),
            {
                "writingPolicyApplied": not degraded,
                "writingPolicyDegraded": degraded,
                "writingPolicyErrorCode": "writing_policy_io_error" if degraded else "",
                "writingPolicyTermCount": 0 if degraded else 1,
                "writingPolicyStyleCount": 0,
                "writingPolicyTruncatedCount": 0,
                "writingPolicyElapsedMs": 3,
                "writingPolicyItemIds": [] if degraded else ["t1"],
            },
        )
        self.audit_calls = []
        self.audit_result = {
            "enabled": not degraded,
            "passed": not degraded,
            "degraded": False,
            "degradedReason": "",
            "summary": (
                "已完成写作规范检查"
                if not degraded
                else "本次未使用写作规范检查"
            ),
            "needsReview": [],
            "expressionSuggestions": [],
        }

    def prepare(self, task_scope, source_parts, scene="auto"):
        self.calls.append((task_scope, list(source_parts), scene))
        return self.result

    def audit(self, match_result, source_text, result_text):
        self.audit_calls.append((match_result, source_text, result_text))
        return dict(self.audit_result)


class RecordingSmartWriteProvider:
    def __init__(self):
        self.calls = []

    def smart_write(
        self,
        text,
        action,
        trace_id,
        user_prompt,
        style,
        focus,
        length,
        selection_mode,
        writing_policy_block,
    ):
        self.calls.append(
            {
                "text": text,
                "action": action,
                "traceId": trace_id,
                "userPrompt": user_prompt,
                "style": style,
                "focus": focus,
                "length": length,
                "selectionMode": selection_mode,
                "writingPolicyBlock": writing_policy_block,
            }
        )
        return {
            "rewrittenText": "智能编写后的正文。",
            "provider": "enterprise-dify-chat/task-file",
        }


class FailingSmartWriteProvider(RecordingSmartWriteProvider):
    def smart_write(self, *args, **kwargs):
        trace_id = args[2]
        record_provider_debug(
            {
                "traceId": trace_id,
                "taskType": "word.smart_write",
                "stage": "request",
                "provider": "enterprise-dify-chat",
                "error": {"type": "ProviderUnavailableError", "message": "provider failed"},
            }
        )
        raise ProviderUnavailableError("provider failed")


class LegacySmartWriteProvider:
    def smart_write(
        self,
        text,
        action,
        trace_id,
        user_prompt,
        style,
        focus,
        length,
        selection_mode,
    ):
        return {
            "rewrittenText": "旧 provider 静默完成。",
            "provider": "legacy-provider",
        }


@unittest.skipUnless(HAS_PYDANTIC, "pydantic is required for smart write tests")
class WordRewriterWritingPolicyTests(unittest.TestCase):
    def _request(
        self,
        plain_text="原始正文。",
        user_instruction="突出风险。",
        writing_policy_scene="auto",
    ):
        return parse_word_request(
            {
                "documentId": "smart-write.docx",
                "scene": "word",
                "selectionMode": "selection",
                "writingPolicyScene": writing_policy_scene,
                "content": {"plainText": plain_text, "paragraphs": [], "headings": []},
                "options": {
                    "rewriteAction": "rewrite",
                    "rewriteStyle": "formal",
                    "focusPoint": "risk",
                    "lengthMode": "same",
                    "userInstruction": user_instruction,
                },
            }
        )

    def test_module_import_does_not_change_writing_policy_environment(self):
        script = "\n".join(
            [
                "import importlib.machinery",
                "import os",
                "import sys",
                "import types",
                "fastapi = types.ModuleType('fastapi')",
                "fastapi.__spec__ = importlib.machinery.ModuleSpec('fastapi', loader=None)",
                "testclient = types.ModuleType('fastapi.testclient')",
                "testclient.TestClient = object",
                "sys.modules['fastapi'] = fastapi",
                "sys.modules['fastapi.testclient'] = testclient",
                "app_main = types.ModuleType('app.main')",
                "app_main.app = object()",
                "sys.modules['app.main'] = app_main",
                "before = os.environ.get('AI_WPS_WRITING_POLICY_DB')",
                "import adapter_service.tests.test_word_rewrite",
                "after = os.environ.get('AI_WPS_WRITING_POLICY_DB')",
                "assert after == before, (before, after)",
            ]
        )
        env = os.environ.copy()
        env["AI_WPS_WRITING_POLICY_DB"] = "discovery-sentinel.db"
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(Path(__file__).resolve().parents[2]),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_smart_write_prepares_and_returns_writing_policy(self):
        provider = RecordingSmartWriteProvider()
        writing_policy = FakeWritingPolicyService()

        result = WordRewriter(provider, writing_policy_service=writing_policy).smart_write(
            self._request(),
            "trace-smart-write-writing_policy",
        )

        self.assertEqual(
            writing_policy.calls,
            [("word.smart_write", ["原始正文。", "突出风险。"], "auto")],
        )
        self.assertEqual(provider.calls[0]["writingPolicyBlock"], writing_policy.result.prompt_block)
        self.assertEqual(provider.calls[0]["text"], "原始正文。")
        self.assertEqual(provider.calls[0]["action"], "rewrite")
        self.assertEqual(provider.calls[0]["userPrompt"], "突出风险。")
        self.assertEqual(provider.calls[0]["selectionMode"], "selection")
        self.assertEqual(result["writingPolicyUsage"], writing_policy.result.usage)
        self.assertEqual(result["writingPolicyAudit"], writing_policy.audit_result)
        self.assertEqual(len(writing_policy.audit_calls), 1)
        self.assertEqual(
            writing_policy.audit_calls[0][1:],
            ("原始正文。", "智能编写后的正文。"),
        )
        self.assertEqual(result["diffHints"], ["Text content changed", "Expanded content length"])

    def test_smart_write_passes_explicit_writing_policy_scene_in_one_provider_call(self):
        provider = RecordingSmartWriteProvider()
        writing_policy = FakeWritingPolicyService()

        result = WordRewriter(
            provider,
            writing_policy_service=writing_policy,
        ).smart_write(
            self._request(writing_policy_scene="cybersecurity"),
            "trace-smart-write-cybersecurity",
        )

        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(
            writing_policy.calls,
            [
                (
                    "word.smart_write",
                    ["原始正文。", "突出风险。"],
                    "cybersecurity",
                )
            ],
        )
        self.assertEqual(result["writingPolicyAudit"]["summary"], "已完成写作规范检查")

    def test_smart_write_resolves_default_writing_policy_only_when_task_runs(self):
        provider = RecordingSmartWriteProvider()
        writing_policy = FakeWritingPolicyService()

        with patch.object(
            rewriter_module,
            "get_writing_policy_service",
            return_value=writing_policy,
        ) as getter:
            rewriter = WordRewriter(provider)
            getter.assert_not_called()

            result = rewriter.smart_write(
                self._request(),
                "trace-smart-write-lazy-writing_policy",
            )

        getter.assert_called_once_with()
        self.assertEqual(provider.calls[0]["writingPolicyBlock"], writing_policy.result.prompt_block)
        self.assertEqual(result["writingPolicyUsage"], writing_policy.result.usage)

    def test_smart_write_degraded_writing_policy_still_calls_provider(self):
        provider = RecordingSmartWriteProvider()
        writing_policy = FakeWritingPolicyService(degraded=True)

        result = WordRewriter(provider, writing_policy_service=writing_policy).smart_write(
            self._request(),
            "trace-smart-write-degraded",
        )

        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(provider.calls[0]["writingPolicyBlock"], "")
        self.assertEqual(result["writingPolicyUsage"], writing_policy.result.usage)
        self.assertTrue(result["writingPolicyUsage"]["degraded"])

    def test_smart_write_defaults_to_human_approved_base_pack_in_one_provider_call(self):
        provider = RecordingSmartWriteProvider()
        with isolated_default_writing_policy_database(self) as db_path:
            rewriter = WordRewriter(provider)
            self.assertFalse(db_path.exists())

            result = rewriter.smart_write(self._request(), "trace-smart-write-default")

            self.assertTrue(db_path.exists())
        self.assertEqual(len(provider.calls), 1)
        self.assertIn("H1 保护项完整", provider.calls[0]["writingPolicyBlock"])
        self.assertTrue(result["writingPolicyUsage"]["applied"])
        self.assertFalse(result["writingPolicyUsage"]["degraded"])
        self.assertEqual(result["writingPolicyUsage"]["termMatchCount"], 0)
        self.assertEqual(result["writingPolicyUsage"]["styleRuleCount"], 8)
        self.assertEqual(result["writingPolicyUsage"]["packName"], "G企技术写作基础")
        self.assertEqual(result["writingPolicyUsage"]["presetVersion"], "1.0.0")

    def test_default_smart_write_injects_enabled_term_from_temporary_sqlite(self):
        provider = RecordingSmartWriteProvider()
        with isolated_default_writing_policy_database(self) as db_path:
            WritingPolicyStore(db_path).create_item(
                {
                    "type": "term",
                    "scope": "global",
                    "category": "系统",
                    "preferredText": "企业大模型接口",
                    "aliases": ["旧模型接口"],
                    "forbiddenVariants": [],
                    "definition": "统一使用企业标准名称。",
                    "contextKeywords": [],
                    "priority": "high",
                    "enabled": True,
                    "note": "Word 默认服务端到端测试",
                }
            )

            result = WordRewriter(provider).smart_write(
                self._request(plain_text="请通过旧模型接口生成正式材料。"),
                "trace-smart-write-real-sqlite",
            )

        writing_policy_block = provider.calls[0]["writingPolicyBlock"]
        self.assertIn("写作规范", writing_policy_block)
        self.assertIn("企业大模型接口", writing_policy_block)
        self.assertTrue(result["writingPolicyUsage"]["applied"])
        self.assertFalse(result["writingPolicyUsage"]["degraded"])
        self.assertEqual(result["writingPolicyUsage"]["termMatchCount"], 1)
        self.assertEqual(result["writingPolicyUsage"]["styleRuleCount"], 8)
        self.assertIn(
            "企业大模型接口",
            [item["name"] for item in result["writingPolicyUsage"]["matchedItems"]],
        )

    def test_smart_write_provider_error_still_merges_writing_policy_debug(self):
        reset_provider_debug()
        writing_policy = FakeWritingPolicyService()

        with self.assertRaises(ProviderUnavailableError):
            WordRewriter(FailingSmartWriteProvider(), writing_policy_service=writing_policy).smart_write(
                self._request(),
                "trace-smart-write-error",
            )

        debug = get_last_provider_debug()
        self.assertEqual(debug["stage"], "request")
        self.assertEqual(debug["provider"], "enterprise-dify-chat")
        self.assertEqual(debug["error"]["type"], "ProviderUnavailableError")
        self.assertTrue(debug["writingPolicyApplied"])
        self.assertEqual(debug["writingPolicyItemIds"], ["t1"])

    def test_smart_write_rejects_provider_without_writing_policy_contract(self):
        with self.assertRaises(TypeError):
            WordRewriter(
                LegacySmartWriteProvider(),
                writing_policy_service=FakeWritingPolicyService(),
            ).smart_write(
                self._request(),
                "trace-smart-write-legacy-provider",
            )

    def test_smart_write_mock_debug_keeps_skip_reason_and_merges_writing_policy(self):
        reset_provider_debug()
        writing_policy = FakeWritingPolicyService()
        provider = ProviderClient(AppSettings(provider_base_url=""))

        result = WordRewriter(provider, writing_policy_service=writing_policy).smart_write(
            self._request(),
            "trace-smart-write-mock",
        )

        debug = get_last_provider_debug()
        self.assertEqual(result["provider"], "mock")
        self.assertNotIn("stage", debug)
        self.assertEqual(debug["skipReason"], "provider_not_configured")
        self.assertEqual(debug["provider"], "mock")
        self.assertTrue(debug["writingPolicyApplied"])


@unittest.skipUnless(HAS_API_DEPS, "fastapi and pydantic are required for API tests")
class WordRewriteApiTests(unittest.TestCase):
    def test_config_then_health_import_does_not_initialize_writing_policy_store(self) -> None:
        script = "\n".join(
            [
                "import os",
                "from unittest.mock import patch",
                "from app.services.writing_policy import service as writing_policy_service_module",
                "from app.services.word import document_reviewer as document_reviewer_module",
                "from app.services.word import rewriter as rewriter_module",
                "from app.services.word import smart_imitator as smart_imitator_module",
                "before = os.environ.get('AI_WPS_WRITING_POLICY_DB')",
                "with patch.object(rewriter_module, 'get_writing_policy_service') as write_getter, \\",
                "     patch.object(smart_imitator_module, 'get_writing_policy_service') as imitation_getter, \\",
                "     patch.object(document_reviewer_module, 'get_writing_policy_service') as review_getter, \\",
                "     patch.object(writing_policy_service_module, 'WritingPolicyStore') as store:",
                "    import adapter_service.tests.test_config",
                "    import adapter_service.tests.test_health",
                "    write_getter.assert_not_called()",
                "    imitation_getter.assert_not_called()",
                "    review_getter.assert_not_called()",
                "    store.assert_not_called()",
                "assert os.environ.get('AI_WPS_WRITING_POLICY_DB') == before",
            ]
        )
        env = os.environ.copy()
        env["AI_WPS_WRITING_POLICY_DB"] = "config-health-import-sentinel.db"
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(Path(__file__).resolve().parents[2]),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_app_main_reload_does_not_initialize_writing_policy_store(self) -> None:
        parent_main_module = sys.modules.get("app.main")
        script = "\n".join(
            [
                "import importlib",
                "import os",
                "from unittest.mock import patch",
                "from app.services.writing_policy import service as writing_policy_service_module",
                "from app.services.word import document_reviewer as document_reviewer_module",
                "from app.services.word import rewriter as rewriter_module",
                "from app.services.word import smart_imitator as smart_imitator_module",
                "before = os.environ.get('AI_WPS_WRITING_POLICY_DB')",
                "with patch.object(rewriter_module, 'get_writing_policy_service') as write_getter, \\",
                "     patch.object(smart_imitator_module, 'get_writing_policy_service') as imitation_getter, \\",
                "     patch.object(document_reviewer_module, 'get_writing_policy_service') as review_getter, \\",
                "     patch.object(writing_policy_service_module, 'WritingPolicyStore') as store:",
                "    import app.api.word as word_api_module",
                "    import app.main as app_main_module",
                "    importlib.reload(word_api_module)",
                "    importlib.reload(app_main_module)",
                "    write_getter.assert_not_called()",
                "    imitation_getter.assert_not_called()",
                "    review_getter.assert_not_called()",
                "    store.assert_not_called()",
                "assert os.environ.get('AI_WPS_WRITING_POLICY_DB') == before",
            ]
        )
        env = os.environ.copy()
        env["AI_WPS_WRITING_POLICY_DB"] = "app-main-reload-sentinel.db"
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(Path(__file__).resolve().parents[2]),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIs(sys.modules.get("app.main"), parent_main_module)

    def test_word_smart_write_returns_workflow_ready_result(self) -> None:
        payload = {
            "documentId": "doc-001",
            "scene": "word",
            "selectionMode": "selection",
            "content": {
                "plainText": "请将这段内容整理得更适合正式材料。",
                "paragraphs": [
                    {
                        "index": 1,
                        "text": "请将这段内容整理得更适合正式材料。",
                        "styleName": "Body",
                        "fontName": "SimSun",
                        "fontSize": 12,
                        "alignment": "left",
                        "outlineLevel": 0
                    }
                ],
                "headings": []
            },
            "options": {
                "templateId": "general-office",
                "trackChanges": True,
                "rewriteAction": "rewrite",
                "rewriteStyle": "formal",
                "focusPoint": "conclusion",
                "lengthMode": "same",
                "userInstruction": "只输出正文"
            }
        }

        with isolated_default_writing_policy_database(self) as db_path:
            client = TestClient(app)
            response = client.post("/word/smart-write", json=payload)

            self.assertTrue(db_path.exists())

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["taskType"], "word.smart_write")
        self.assertEqual(body["data"]["rewriteMode"], "rewrite")
        self.assertTrue(body["data"]["rewrittenText"])
        self.assertIn("Text content changed", body["data"]["diffHints"])
