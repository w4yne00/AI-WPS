import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class PackagingScriptTests(unittest.TestCase):
    def test_uvicorn_start_script_replaces_stale_running_adapter(self) -> None:
        script = (ROOT / "adapter-start-kit/scripts/start_uvicorn_adapter.sh").read_text(encoding="utf-8")

        self.assertIn("EXPECTED_VERSION", script)
        self.assertIn("CURRENT_VERSION", script)
        self.assertIn("replace_existing_adapter", script)
        self.assertIn("adapter_stale_running", script)

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

    def test_taskpane_settings_exposes_task_route_keys(self) -> None:
        html = (ROOT / "formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html").read_text(
            encoding="utf-8"
        )
        js = (ROOT / "formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js").read_text(encoding="utf-8")

        self.assertIn("task-routes-list", html)
        self.assertIn("renderTaskRoutes", js)
        self.assertIn("/provider/task-api-key", js)
