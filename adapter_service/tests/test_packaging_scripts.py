import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class PackagingScriptTests(unittest.TestCase):
    def test_uvicorn_start_script_replaces_stale_running_adapter(self) -> None:
        script = (ROOT / "adapter-start-kit/scripts/start_uvicorn_adapter.sh").read_text(encoding="utf-8")

        self.assertIn("EXPECTED_VERSION", script)
        self.assertIn("CURRENT_VERSION", script)
        self.assertIn('EXPECTED_VERSION="${EXPECTED_VERSION:-0.12.0-alpha}"', script)
        self.assertIn("replace_existing_adapter", script)
        self.assertIn("adapter_stale_running", script)

    def test_adapter_operations_scripts_manage_uvicorn_and_provider_diagnostics(self) -> None:
        scripts = {
            name: (ROOT / "adapter-start-kit/scripts" / name).read_text(encoding="utf-8")
            for name in [
                "start_adapter.sh",
                "restart_adapter.sh",
                "status_adapter.sh",
                "check_health.sh",
                "show_logs.sh",
                "stop_adapter.sh",
            ]
        }

        self.assertIn("start_uvicorn_adapter.sh", scripts["start_adapter.sh"])
        self.assertIn("start_uvicorn_adapter.sh", scripts["restart_adapter.sh"])
        self.assertIn("/provider/status", scripts["status_adapter.sh"])
        self.assertIn("/provider/route-diagnostics", scripts["check_health.sh"])
        self.assertIn("/provider/debug-last", scripts["check_health.sh"])
        self.assertIn("provider=mock", scripts["show_logs.sh"])
        self.assertIn("stop_port_listener", scripts["stop_adapter.sh"])

    def test_taskpane_technical_review_has_three_document_types_and_prompt_map(self) -> None:
        html = (ROOT / "formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html").read_text(
            encoding="utf-8"
        )
        js = (ROOT / "formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js").read_text(encoding="utf-8")

        self.assertNotIn('value="general_technical"', html)
        self.assertIn('value="technical_solution"', html)
        self.assertIn('value="contract_acceptance"', html)
        self.assertIn('value="test_outline"', html)
        self.assertIn("TECHNICAL_REVIEW_PROMPTS", js)
        self.assertIn("applyTechnicalReviewPrompt", js)

    def test_taskpane_merges_fallback_templates(self) -> None:
        js = (ROOT / "formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js").read_text(encoding="utf-8")

        self.assertIn("mergeTemplates", js)
        self.assertIn("technical-file-format-requirements", js)

    def test_taskpane_settings_exposes_unified_and_task_api_keys_without_probe(self) -> None:
        html = (ROOT / "formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html").read_text(
            encoding="utf-8"
        )
        js = (ROOT / "formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js").read_text(encoding="utf-8")

        self.assertNotIn("renderTaskRoutes", js)
        self.assertIn("task-api-key-list", html)
        self.assertIn("/provider/task-api-key", js)
        self.assertIn("word.smart_format", js)
        self.assertIn('id="provider-auth-line"', html)
        self.assertIn("setProviderAuthLine", js)
        self.assertIn("providerAuthSource", js)
        self.assertIn('id="provider-api-key"', html)
        self.assertIn('id="btn-save-api-key"', html)
        self.assertIn('id="btn-clear-api-key"', html)
        self.assertNotIn('id="btn-probe"', html)
        self.assertNotIn("runProbe", js)

    def test_smart_write_taskpane_exposes_prompt_fragments(self) -> None:
        html = (ROOT / "formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html").read_text(
            encoding="utf-8"
        )
        js = (ROOT / "formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js").read_text(encoding="utf-8")

        self.assertIn("智能编写", html)
        self.assertIn('id="write-action"', html)
        self.assertIn("prompt-fragment-card", html)
        self.assertIn('id="prompt-fragment-card" class="prompt-fragment-card" hidden', html)
        self.assertIn("rewrite-prompt-label", html)
        self.assertIn("补充要求：请突出风险和下一步计划，压缩到200字以内。", html)
        self.assertIn("updateRewritePromptPreview", js)
        self.assertIn("showPromptFragments: true", js)
        self.assertIn("prompt-fragment-card\").hidden = !shouldShowPromptFragments", js)
        self.assertIn("REWRITE_STYLE_PROMPTS", js)
        self.assertIn("不要原样返回待处理内容", js)
        self.assertIn("/word/smart-write", js)
        self.assertNotIn("/word/rewrite", js)

    def test_ribbon_uses_five_current_entries_and_current_icons(self) -> None:
        ribbon = (ROOT / "formal-plugin-kit/wps-ai-assistant_1.0.0/ribbon.xml").read_text(
            encoding="utf-8"
        )
        ribbon_js = (ROOT / "formal-plugin-kit/wps-ai-assistant_1.0.0/ribbon.js").read_text(
            encoding="utf-8"
        )

        for label in ["智能编写", "格式校对", "智能排版", "技术文档审查", "设置"]:
            self.assertIn('label="{0}"'.format(label), ribbon)
        self.assertNotIn("智能改写", ribbon)
        self.assertNotIn("智能续写", ribbon)
        self.assertIn("btnAiSmartWrite", ribbon)
        self.assertNotIn("btnAiRewrite", ribbon)
        self.assertNotIn("btnAiContinue", ribbon)
        self.assertIn("icon-smart-write.png", ribbon_js)
        self.assertIn("icon-review.png", ribbon_js)
