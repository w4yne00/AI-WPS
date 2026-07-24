import importlib
import importlib.util
import unittest
from pathlib import Path

from app.core.models import (
    RewriteResponseData,
    WordDocumentRequest,
    WritingPolicyAudit,
    WritingPolicyUsage,
)


HAS_FASTAPI = importlib.util.find_spec("fastapi") is not None
if HAS_FASTAPI:
    from app.main import app


ROOT = Path(__file__).resolve().parents[2]
ADAPTER_RUNTIME = ROOT / "adapter_service"
FORMAL_PLUGIN = ROOT / "formal-plugin-kit"
WORD_PLUGIN = FORMAL_PLUGIN / "wps-ai-assistant_1.0.0"
EXCEL_PLUGIN = FORMAL_PLUGIN / "wps-ai-assistant-et_1.0.0"
PPT_PLUGIN = FORMAL_PLUGIN / "wps-ai-assistant-wpp_1.0.0"


def _read_tree(root: Path, suffixes=(".py", ".js", ".html")) -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.suffix in suffixes
    )


class WritingPolicyScopeContractTests(unittest.TestCase):
    def test_public_python_package_uses_writing_policy_name(self):
        module = importlib.import_module("app.services.writing_policy")
        self.assertTrue(hasattr(module, "WritingPolicyService"))
        with self.assertRaises(ModuleNotFoundError):
            importlib.import_module("app.services.enterprise_knowledge")

    @unittest.skipUnless(HAS_FASTAPI, "FastAPI dependency is not installed")
    def test_management_routes_expose_only_writing_policy_prefix(self):
        route_paths = {route.path for route in app.routes}
        self.assertIn("/writing-policies/summary", route_paths)
        self.assertIn("/writing-policies/items", route_paths)
        self.assertFalse(any(path.startswith("/enterprise-knowledge") for path in route_paths))

    def test_word_request_and_response_use_confirmed_json_vocabulary(self):
        request = WordDocumentRequest.model_validate(
            {
                "documentId": "demo.docx",
                "writingPolicyScene": "auto",
                "content": {"plainText": "示例"},
            }
        )
        self.assertEqual(request.writing_policy_scene, "auto")

        result = RewriteResponseData.model_validate(
            {
                "originalText": "原文",
                "rewrittenText": "结果",
                "rewriteMode": "rewrite",
                "writingPolicyUsage": {
                    "applied": True,
                    "termMatchCount": 1,
                },
                "writingPolicyAudit": {
                    "needsReview": [],
                    "expressionSuggestions": [],
                },
            }
        ).model_dump(by_alias=True)

        self.assertIsInstance(result["writingPolicyUsage"], dict)
        self.assertEqual(result["writingPolicyAudit"]["needsReview"], [])
        self.assertNotIn("knowledgeUsage", result)
        self.assertEqual(
            RewriteResponseData.model_fields["writing_policy_usage"].alias,
            "writingPolicyUsage",
        )
        self.assertEqual(
            RewriteResponseData.model_fields["writing_policy_audit"].alias,
            "writingPolicyAudit",
        )

    def test_runtime_sources_contain_no_legacy_contract_names(self):
        runtime_source = "\n".join(
            (
                _read_tree(ADAPTER_RUNTIME / "app"),
                (ADAPTER_RUNTIME / "standalone_adapter.py").read_text(encoding="utf-8"),
                _read_tree(WORD_PLUGIN, suffixes=(".js", ".html")),
            )
        )
        for legacy_name in (
            "enterprise_knowledge",
            "enterprise-knowledge",
            "enterpriseKnowledge",
            "EnterpriseKnowledge",
            "knowledgeUsage",
            "enterprise_knowledge_block",
            "_enterprise_",
            "ENTERPRISE_JSON_REQUEST_TOO_LARGE",
        ):
            self.assertNotIn(legacy_name, runtime_source)

    def test_writing_policy_ui_and_runtime_are_word_only(self):
        word_source = _read_tree(WORD_PLUGIN, suffixes=(".js", ".html"))
        self.assertIn("writingPolicyUsage", word_source)
        self.assertIn("/writing-policies/summary", word_source)
        self.assertIn("写作规范库", word_source)

        for plugin_root in (EXCEL_PLUGIN, PPT_PLUGIN):
            host_source = _read_tree(plugin_root, suffixes=(".js", ".html"))
            self.assertNotIn("/writing-policies", host_source)
            self.assertNotIn("writingPolicyScene", host_source)
            self.assertNotIn("writingPolicyUsage", host_source)

    def test_protected_non_word_services_do_not_load_writing_policy(self):
        format_review_source = (
            ADAPTER_RUNTIME / "app/services/word/format_reviewer.py"
        ).read_text(encoding="utf-8")
        excel_source = _read_tree(ADAPTER_RUNTIME / "app/services/excel")
        ppt_source = _read_tree(ADAPTER_RUNTIME / "app/services/ppt")

        for source in (format_review_source, excel_source, ppt_source):
            self.assertNotIn("writing_policy", source)


if __name__ == "__main__":
    unittest.main()
