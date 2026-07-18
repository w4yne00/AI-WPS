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
    from app.services.enterprise_knowledge import KnowledgeMatchResult
    from app.services.enterprise_knowledge import service as knowledge_service_module
    from app.services.enterprise_knowledge.store import EnterpriseKnowledgeStore
    from app.services.provider_client import (
        ProviderClient,
        get_last_provider_debug,
        record_provider_debug,
        reset_provider_debug,
    )
    from app.services.word import rewriter as rewriter_module
    from app.services.word.rewriter import WordRewriter


PROJECT_KNOWLEDGE_DB = Path(__file__).resolve().parents[2] / "run" / "enterprise_knowledge.db"
_MISSING_ENV = object()


def database_signature(path):
    try:
        stat_result = path.stat()
    except FileNotFoundError:
        return None
    return (stat_result.st_mtime_ns, stat_result.st_size)


def restore_database_env(previous):
    if previous is _MISSING_ENV:
        os.environ.pop("AI_WPS_ENTERPRISE_KNOWLEDGE_DB", None)
    else:
        os.environ["AI_WPS_ENTERPRISE_KNOWLEDGE_DB"] = previous


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
            restore_database_env(previous)
            test_case.assertEqual(
                database_signature(PROJECT_KNOWLEDGE_DB),
                project_signature,
            )


if HAS_API_DEPS:
    from fastapi.testclient import TestClient

    from app.main import app


def parse_word_request(payload):
    if hasattr(WordDocumentRequest, "model_validate"):
        return WordDocumentRequest.model_validate(payload)
    return WordDocumentRequest.parse_obj(payload)


class FakeKnowledgeService:
    def __init__(self, prompt_block="企业术语与写作规范（必须遵守）：\n- 使用标准术语。", degraded=False):
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
            "" if degraded else prompt_block,
            self.usage,
            () if degraded else ("t1",),
            {
                "knowledgeApplied": not degraded,
                "knowledgeDegraded": degraded,
                "knowledgeErrorCode": "knowledge_io_error" if degraded else "",
                "knowledgeTermCount": 0 if degraded else 1,
                "knowledgeStyleCount": 0,
                "knowledgeTruncatedCount": 0,
                "knowledgeElapsedMs": 3,
                "knowledgeItemIds": [] if degraded else ["t1"],
            },
        )

    def prepare(self, task_scope, source_parts):
        self.calls.append((task_scope, list(source_parts)))
        return self.result


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
        enterprise_knowledge_block,
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
                "enterpriseKnowledgeBlock": enterprise_knowledge_block,
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
class WordRewriterKnowledgeTests(unittest.TestCase):
    def _request(self, plain_text="原始正文。", user_instruction="突出风险。"):
        return parse_word_request(
            {
                "documentId": "smart-write.docx",
                "scene": "word",
                "selectionMode": "selection",
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

    def test_module_import_does_not_change_enterprise_knowledge_environment(self):
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
                "before = os.environ.get('AI_WPS_ENTERPRISE_KNOWLEDGE_DB')",
                "import adapter_service.tests.test_word_rewrite",
                "after = os.environ.get('AI_WPS_ENTERPRISE_KNOWLEDGE_DB')",
                "assert after == before, (before, after)",
            ]
        )
        env = os.environ.copy()
        env["AI_WPS_ENTERPRISE_KNOWLEDGE_DB"] = "discovery-sentinel.db"
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(Path(__file__).resolve().parents[2]),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_smart_write_prepares_and_returns_enterprise_knowledge(self):
        provider = RecordingSmartWriteProvider()
        knowledge = FakeKnowledgeService()

        result = WordRewriter(provider, knowledge_service=knowledge).smart_write(
            self._request(),
            "trace-smart-write-knowledge",
        )

        self.assertEqual(
            knowledge.calls,
            [("word.smart_write", ["原始正文。", "突出风险。"])],
        )
        self.assertEqual(provider.calls[0]["enterpriseKnowledgeBlock"], knowledge.result.prompt_block)
        self.assertEqual(provider.calls[0]["text"], "原始正文。")
        self.assertEqual(provider.calls[0]["action"], "rewrite")
        self.assertEqual(provider.calls[0]["userPrompt"], "突出风险。")
        self.assertEqual(provider.calls[0]["selectionMode"], "selection")
        self.assertEqual(result["knowledgeUsage"], knowledge.result.usage)
        self.assertEqual(result["diffHints"], ["Text content changed", "Expanded content length"])

    def test_smart_write_resolves_default_knowledge_only_when_task_runs(self):
        provider = RecordingSmartWriteProvider()
        knowledge = FakeKnowledgeService()

        with patch.object(
            rewriter_module,
            "get_enterprise_knowledge_service",
            return_value=knowledge,
        ) as getter:
            rewriter = WordRewriter(provider)
            getter.assert_not_called()

            result = rewriter.smart_write(
                self._request(),
                "trace-smart-write-lazy-knowledge",
            )

        getter.assert_called_once_with()
        self.assertEqual(provider.calls[0]["enterpriseKnowledgeBlock"], knowledge.result.prompt_block)
        self.assertEqual(result["knowledgeUsage"], knowledge.result.usage)

    def test_smart_write_degraded_knowledge_still_calls_provider(self):
        provider = RecordingSmartWriteProvider()
        knowledge = FakeKnowledgeService(degraded=True)

        result = WordRewriter(provider, knowledge_service=knowledge).smart_write(
            self._request(),
            "trace-smart-write-degraded",
        )

        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(provider.calls[0]["enterpriseKnowledgeBlock"], "")
        self.assertEqual(result["knowledgeUsage"], knowledge.result.usage)
        self.assertTrue(result["knowledgeUsage"]["degraded"])

    def test_smart_write_defaults_to_empty_enterprise_knowledge_service(self):
        provider = RecordingSmartWriteProvider()
        with isolated_default_knowledge_database(self) as db_path:
            rewriter = WordRewriter(provider)
            self.assertFalse(db_path.exists())

            result = rewriter.smart_write(self._request(), "trace-smart-write-default")

            self.assertTrue(db_path.exists())
        self.assertEqual(provider.calls[0]["enterpriseKnowledgeBlock"], "")
        self.assertTrue(result["knowledgeUsage"]["applied"])
        self.assertFalse(result["knowledgeUsage"]["degraded"])
        self.assertEqual(result["knowledgeUsage"]["termMatchCount"], 0)
        self.assertEqual(result["knowledgeUsage"]["matchedItems"], [])

    def test_default_smart_write_injects_enabled_term_from_temporary_sqlite(self):
        provider = RecordingSmartWriteProvider()
        with isolated_default_knowledge_database(self) as db_path:
            EnterpriseKnowledgeStore(db_path).create_item(
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

        knowledge_block = provider.calls[0]["enterpriseKnowledgeBlock"]
        self.assertIn("企业术语与写作规范", knowledge_block)
        self.assertIn("企业大模型接口", knowledge_block)
        self.assertTrue(result["knowledgeUsage"]["applied"])
        self.assertFalse(result["knowledgeUsage"]["degraded"])
        self.assertEqual(result["knowledgeUsage"]["termMatchCount"], 1)
        self.assertEqual(len(result["knowledgeUsage"]["matchedItems"]), 1)

    def test_smart_write_provider_error_still_merges_knowledge_debug(self):
        reset_provider_debug()
        knowledge = FakeKnowledgeService()

        with self.assertRaises(ProviderUnavailableError):
            WordRewriter(FailingSmartWriteProvider(), knowledge_service=knowledge).smart_write(
                self._request(),
                "trace-smart-write-error",
            )

        debug = get_last_provider_debug()
        self.assertEqual(debug["stage"], "request")
        self.assertEqual(debug["provider"], "enterprise-dify-chat")
        self.assertEqual(debug["error"]["type"], "ProviderUnavailableError")
        self.assertTrue(debug["knowledgeApplied"])
        self.assertEqual(debug["knowledgeItemIds"], ["t1"])

    def test_smart_write_rejects_provider_without_enterprise_knowledge_contract(self):
        with self.assertRaises(TypeError):
            WordRewriter(
                LegacySmartWriteProvider(),
                knowledge_service=FakeKnowledgeService(),
            ).smart_write(
                self._request(),
                "trace-smart-write-legacy-provider",
            )

    def test_smart_write_mock_debug_keeps_skip_reason_and_merges_knowledge(self):
        reset_provider_debug()
        knowledge = FakeKnowledgeService()
        provider = ProviderClient(AppSettings(provider_base_url=""))

        result = WordRewriter(provider, knowledge_service=knowledge).smart_write(
            self._request(),
            "trace-smart-write-mock",
        )

        debug = get_last_provider_debug()
        self.assertEqual(result["provider"], "mock")
        self.assertNotIn("stage", debug)
        self.assertEqual(debug["skipReason"], "provider_not_configured")
        self.assertEqual(debug["provider"], "mock")
        self.assertTrue(debug["knowledgeApplied"])


@unittest.skipUnless(HAS_API_DEPS, "fastapi and pydantic are required for API tests")
class WordRewriteApiTests(unittest.TestCase):
    def test_config_then_health_import_does_not_initialize_enterprise_knowledge_store(self) -> None:
        script = "\n".join(
            [
                "import os",
                "from unittest.mock import patch",
                "from app.services.enterprise_knowledge import service as knowledge_service_module",
                "from app.services.word import document_reviewer as document_reviewer_module",
                "from app.services.word import rewriter as rewriter_module",
                "from app.services.word import smart_imitator as smart_imitator_module",
                "before = os.environ.get('AI_WPS_ENTERPRISE_KNOWLEDGE_DB')",
                "with patch.object(rewriter_module, 'get_enterprise_knowledge_service') as write_getter, \\",
                "     patch.object(smart_imitator_module, 'get_enterprise_knowledge_service') as imitation_getter, \\",
                "     patch.object(document_reviewer_module, 'get_enterprise_knowledge_service') as review_getter, \\",
                "     patch.object(knowledge_service_module, 'EnterpriseKnowledgeStore') as store:",
                "    import adapter_service.tests.test_config",
                "    import adapter_service.tests.test_health",
                "    write_getter.assert_not_called()",
                "    imitation_getter.assert_not_called()",
                "    review_getter.assert_not_called()",
                "    store.assert_not_called()",
                "assert os.environ.get('AI_WPS_ENTERPRISE_KNOWLEDGE_DB') == before",
            ]
        )
        env = os.environ.copy()
        env["AI_WPS_ENTERPRISE_KNOWLEDGE_DB"] = "config-health-import-sentinel.db"
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(Path(__file__).resolve().parents[2]),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_app_main_reload_does_not_initialize_enterprise_knowledge_store(self) -> None:
        parent_main_module = sys.modules.get("app.main")
        script = "\n".join(
            [
                "import importlib",
                "import os",
                "from unittest.mock import patch",
                "from app.services.enterprise_knowledge import service as knowledge_service_module",
                "from app.services.word import document_reviewer as document_reviewer_module",
                "from app.services.word import rewriter as rewriter_module",
                "from app.services.word import smart_imitator as smart_imitator_module",
                "before = os.environ.get('AI_WPS_ENTERPRISE_KNOWLEDGE_DB')",
                "with patch.object(rewriter_module, 'get_enterprise_knowledge_service') as write_getter, \\",
                "     patch.object(smart_imitator_module, 'get_enterprise_knowledge_service') as imitation_getter, \\",
                "     patch.object(document_reviewer_module, 'get_enterprise_knowledge_service') as review_getter, \\",
                "     patch.object(knowledge_service_module, 'EnterpriseKnowledgeStore') as store:",
                "    import app.api.word as word_api_module",
                "    import app.main as app_main_module",
                "    importlib.reload(word_api_module)",
                "    importlib.reload(app_main_module)",
                "    write_getter.assert_not_called()",
                "    imitation_getter.assert_not_called()",
                "    review_getter.assert_not_called()",
                "    store.assert_not_called()",
                "assert os.environ.get('AI_WPS_ENTERPRISE_KNOWLEDGE_DB') == before",
            ]
        )
        env = os.environ.copy()
        env["AI_WPS_ENTERPRISE_KNOWLEDGE_DB"] = "app-main-reload-sentinel.db"
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

        with isolated_default_knowledge_database(self) as db_path:
            client = TestClient(app)
            response = client.post("/word/smart-write", json=payload)

            self.assertTrue(db_path.exists())

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["taskType"], "word.smart_write")
        self.assertEqual(body["data"]["rewriteMode"], "rewrite")
        self.assertTrue(body["data"]["rewrittenText"])
        self.assertIn("Text content changed", body["data"]["diffHints"])
