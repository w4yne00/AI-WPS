import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class PackagingScriptTests(unittest.TestCase):
    def test_uvicorn_start_script_replaces_stale_running_adapter(self) -> None:
        script = (ROOT / "adapter-start-kit/scripts/start_uvicorn_adapter.sh").read_text(encoding="utf-8")

        self.assertIn("EXPECTED_VERSION", script)
        self.assertIn("CURRENT_VERSION", script)
        self.assertIn('EXPECTED_VERSION="${EXPECTED_VERSION:-0.19.1-alpha}"', script)
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

    def test_standalone_adapter_exposes_workflow_profile_management(self) -> None:
        script = (ROOT / "adapter_service/standalone_adapter.py").read_text(encoding="utf-8")

        self.assertIn('path == "/provider/workflow-profiles"', script)
        self.assertIn("def do_PATCH", script)
        self.assertIn('path.endswith("/activate")', script)
        self.assertIn('path.endswith("/api-key")', script)
        self.assertIn("WorkflowProfileStore", script)

    def test_standalone_adapter_exposes_ppt_background_routes(self) -> None:
        script = (ROOT / "adapter_service/standalone_adapter.py").read_text(encoding="utf-8")

        self.assertIn("def parse_ppt_request", script)
        self.assertIn("def ppt_slide_assistant_job_payload", script)
        self.assertIn('path == "/ppt/slide-assistant/jobs"', script)
        self.assertIn('path.startswith("/ppt/slide-assistant/jobs/")', script)
        self.assertIn("PPT_SLIDE_JOB_NOT_FOUND", script)

    def test_adapter_autostart_scripts_install_systemd_service(self) -> None:
        install_script = (ROOT / "adapter-start-kit/scripts/install_autostart.sh").read_text(
            encoding="utf-8"
        )
        uninstall_script = (ROOT / "adapter-start-kit/scripts/uninstall_autostart.sh").read_text(
            encoding="utf-8"
        )
        guide = (ROOT / "adapter-start-kit/docs/autostart-guide.md").read_text(encoding="utf-8")

        self.assertIn("ai-wps-adapter.service", install_script)
        self.assertIn("systemctl enable --now", install_script)
        self.assertIn("ExecStart=", install_script)
        self.assertIn("scripts/start_adapter.sh", install_script)
        self.assertIn("Restart=on-failure", install_script)
        self.assertIn("User=", install_script)
        self.assertIn("systemctl disable --now", uninstall_script)
        self.assertIn("daemon-reload", uninstall_script)
        self.assertIn("开机自启动", guide)
        self.assertIn("bash scripts/install_autostart.sh", guide)

    def test_phase1_delivery_includes_smart_write_dify_manual(self) -> None:
        script = (ROOT / "packaging/build_phase1_delivery_kit.sh").read_text(encoding="utf-8")

        self.assertIn("dify-smart-write-workflow.md", script)
        self.assertIn("dify-smart-imitation-workflow.md", script)
        self.assertIn("dify-document-review-workflow.md", script)
        self.assertIn("dify-format-review-workflow.md", script)
        self.assertIn("dify-excel-analysis-workflow.md", script)

    def test_delivery_includes_excel_and_ppt_prompt_templates(self) -> None:
        script = (ROOT / "packaging/build_phase1_delivery_kit.sh").read_text(encoding="utf-8")

        self.assertIn("docs/prompt-templates", script)
        template_names = [
            "excel-smart-analysis-prompt-template.md",
            "ppt-smart-summary-prompt-template.md",
        ]
        for name in template_names:
            self.assertIn(name, script)
            template_path = ROOT / "docs/prompt-templates" / name
            self.assertTrue(template_path.is_file(), f"missing prompt template: {name}")
            text = template_path.read_text(encoding="utf-8")
            for required_text in [
                "适用任务",
                "输入",
                "System Prompt",
                "变量",
                "输出契约",
                "<think>",
                "max token",
                "错误",
                "禁止事项",
            ]:
                self.assertIn(required_text, text)
            self.assertNotIn("Bearer sk-", text)
            self.assertNotIn("provider_api_key", text)

    def test_phase1_packaging_includes_word_and_excel_addins(self) -> None:
        script = (ROOT / "packaging/build_phase1_delivery_kit.sh").read_text(encoding="utf-8")

        self.assertIn("WORD_FORMAL_SRC", script)
        self.assertIn("EXCEL_FORMAL_SRC", script)
        self.assertIn("wps-ai-assistant_1.0.0", script)
        self.assertIn("wps-ai-assistant-et_1.0.0", script)

    def test_phase1_packaging_includes_all_three_host_addins_and_ppt_guide(self) -> None:
        script = (ROOT / "packaging/build_phase1_delivery_kit.sh").read_text(encoding="utf-8")

        self.assertIn("PPT_FORMAL_SRC", script)
        self.assertIn("wps-ai-assistant-wpp_1.0.0", script)
        self.assertIn("dify-ppt-slide-assistant-workflow.md", script)

    def test_phase1_installer_installs_word_and_excel_addins(self) -> None:
        script = (ROOT / "phase1-delivery-kit/installer/install_phase1.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn('WORD_PLUGIN_NAME="wps-ai-assistant_1.0.0"', script)
        self.assertIn('EXCEL_PLUGIN_NAME="wps-ai-assistant-et_1.0.0"', script)
        self.assertIn('name="wps-ai-assistant"', script)
        self.assertIn('type="wps"', script)
        self.assertIn('name="wps-ai-assistant-et"', script)
        self.assertIn('type="et"', script)
        self.assertIn('grep -v \'name="wps-ai-assistant"\'', script)
        self.assertIn('grep -v \'name="wps-ai-assistant-et"\'', script)
        self.assertIn("preserve_adapter_runtime_config", script)
        self.assertIn("restore_adapter_runtime_config", script)

    def test_phase1_installer_installs_ppt_addin_in_same_package(self) -> None:
        installer = (ROOT / "phase1-delivery-kit/installer/install_phase1.sh").read_text(
            encoding="utf-8"
        )
        publish_xml = (ROOT / "phase1-delivery-kit/wps-jsaddons/publish.xml").read_text(
            encoding="utf-8"
        )

        self.assertIn('PPT_PLUGIN_NAME="wps-ai-assistant-wpp_1.0.0"', installer)
        self.assertIn('name="wps-ai-assistant-wpp"', installer)
        self.assertIn('type="wpp"', installer)
        self.assertIn('grep -v \'name="wps-ai-assistant-wpp"\'', installer)
        self.assertIn('name="wps-ai-assistant-wpp"', publish_xml)
        self.assertIn('type="wpp"', publish_xml)
        self.assertIn("preserve_adapter_runtime_config", installer)
        self.assertIn("config/adapter.json", installer)
        self.assertIn("provider_api_key", installer)
        self.assertIn("provider_api_keys", installer)

    def test_smart_imitation_icon_and_config_are_packaged(self) -> None:
        self.assertTrue(
            (ROOT / "formal-plugin-kit/wps-ai-assistant_1.0.0/assets/icon-smart-imitation.png").exists()
        )
        self.assertTrue((ROOT / "docs/operations/dify-smart-imitation-workflow.md").exists())
        config = (ROOT / "config/adapter.example.json").read_text(encoding="utf-8")
        self.assertIn('"word.smart_imitation": "word_smart_imitation"', config)

    def test_phase1_installer_preserves_adapter_runtime_configuration(self) -> None:
        script = (ROOT / "phase1-delivery-kit/installer/install_phase1.sh").read_text(encoding="utf-8")

        self.assertIn("preserve_adapter_runtime_config", script)
        self.assertIn("restore_adapter_runtime_config", script)
        self.assertIn("config/adapter.json", script)
        self.assertIn("run/provider_api_key", script)
        self.assertIn("run/provider_api_keys", script)
        self.assertNotIn('copy_dir "$ADAPTER_SOURCE" "$ADAPTER_TARGET"', script)

    def test_phase1_installer_preserves_writing_policy_database(self) -> None:
        script = (ROOT / "phase1-delivery-kit/installer/install_phase1.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn("run/writing_policies.db", script)
        self.assertIn("writing_policies.db.backup-*", script)
        self.assertIn("preserve_adapter_runtime_config", script)
        self.assertIn("restore_adapter_runtime_config", script)
        self.assertIn('[ -e "$writing_policy_backup" ] || continue', script)

    def test_phase1_installer_restores_live_writing_policy_files_after_replacement(self) -> None:
        installer = (ROOT / "phase1-delivery-kit/installer/install_phase1.sh").read_text(
            encoding="utf-8"
        )
        function_prefix = installer.split("enable_exec_permissions() {", 1)[0]

        with tempfile.TemporaryDirectory() as temp_dir:
            adapter_target = Path(temp_dir) / "adapter-start-kit"
            run_dir = adapter_target / "run"
            run_dir.mkdir(parents=True)
            (run_dir / "writing_policies.db").write_text("live-db", encoding="utf-8")
            for index in range(1, 6):
                (run_dir / f"writing_policies.db.backup-{index}").write_text(
                    f"backup-{index}", encoding="utf-8"
                )

            harness = Path(temp_dir) / "preserve-test.sh"
            harness.write_text(
                function_prefix
                + "\nADAPTER_TARGET=\"$1\"\n"
                + "ADAPTER_CONFIG_BACKUP=\"\"\n"
                + "preserve_adapter_runtime_config\n"
                + "rm -rf \"$ADAPTER_TARGET\"\n"
                + "mkdir -p \"$ADAPTER_TARGET/run\"\n"
                + "restore_adapter_runtime_config\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                ["bash", str(harness), str(adapter_target)],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                (run_dir / "writing_policies.db").read_text(encoding="utf-8"),
                "live-db",
            )
            restored_backups = sorted(run_dir.glob("writing_policies.db.backup-*"))
            self.assertEqual(
                [path.name for path in restored_backups],
                [
                    "writing_policies.db.backup-3",
                    "writing_policies.db.backup-4",
                    "writing_policies.db.backup-5",
                ],
            )

    def test_phase1_delivery_generates_writing_policy_templates_and_includes_guide(self) -> None:
        script = (ROOT / "packaging/build_phase1_delivery_kit.sh").read_text(
            encoding="utf-8"
        )
        guide = ROOT / "docs/operations/writing-policy-library.md"

        self.assertIn("docs/import-templates", script)
        self.assertIn("generate_csv_template", script)
        self.assertIn("generate_xlsx_template", script)
        self.assertIn("writing-policies-import-template.csv", script)
        self.assertIn("writing-policies-import-template.xlsx", script)
        self.assertIn("writing-policy-library.md", script)
        self.assertIn("writing-policy-sources.md", script)
        self.assertIn('cp -R "$ROOT_DIR/adapter_service"', script)
        self.assertTrue(guide.is_file(), "missing writing policy operations guide")
        self.assertTrue(
            (ROOT / "adapter_service/writing_policy_packs/yangqi-tech-writing-base.json").is_file()
        )
        self.assertTrue(
            (ROOT / "adapter_service/writing_policy_packs/THIRD_PARTY_NOTICES.md").is_file()
        )

        text = guide.read_text(encoding="utf-8")
        for required_text in [
            "全局术语",
            "智能编写",
            "智能仿写",
            "文档审查",
            "5 MB",
            "|",
            "保留库内标准",
            "CSV 导出",
            "完整备份",
            "降级",
            "diagnostics",
            "损坏",
        ]:
            self.assertIn(required_text, text)

    def test_phase1_delivery_uses_v0191_release_name(self) -> None:
        script = (ROOT / "packaging/build_phase1_delivery_kit.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn('KIT_NAME="ai-wps-phase1-delivery-${DATE_TAG}-v0191"', script)

    def test_taskpane_document_review_has_three_document_types_and_prompt_map(self) -> None:
        html = (ROOT / "formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html").read_text(
            encoding="utf-8"
        )
        js = (ROOT / "formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js").read_text(encoding="utf-8")

        self.assertNotIn('value="general_technical"', html)
        self.assertIn('value="technical_solution"', html)
        self.assertIn('value="contract_acceptance"', html)
        self.assertIn('value="test_outline"', html)
        self.assertIn("DOCUMENT_REVIEW_PROMPTS", js)
        self.assertIn("applyDocumentReviewPrompt", js)

    def test_taskpane_merges_fallback_templates(self) -> None:
        js = (ROOT / "formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js").read_text(encoding="utf-8")

        self.assertIn("mergeTemplates", js)
        self.assertIn("technical-file-format-requirements", js)

    def test_taskpane_settings_hides_unified_key_but_keeps_compatibility(self) -> None:
        host_dirs = [
            "wps-ai-assistant_1.0.0",
            "wps-ai-assistant-et_1.0.0",
            "wps-ai-assistant-wpp_1.0.0",
        ]
        host_files = [
            (
                ROOT / "formal-plugin-kit" / host_dir / "taskpane.html",
                ROOT / "formal-plugin-kit" / host_dir / "taskpane.js",
            )
            for host_dir in host_dirs
        ]
        html = host_files[0][0].read_text(encoding="utf-8")
        js = host_files[0][1].read_text(encoding="utf-8")
        standalone = (ROOT / "adapter_service/standalone_adapter.py").read_text(encoding="utf-8")
        installer = (ROOT / "phase1-delivery-kit/installer/install_phase1.sh").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("renderTaskRoutes", js)
        self.assertIn("workflow-profile-manager", html)
        self.assertIn("workflow-profile-select", html)
        self.assertIn("/provider/workflow-profiles", js)
        self.assertIn("word.smart_write", js)
        self.assertIn("word.smart_imitation", js)
        self.assertIn("word.document_review", js)
        self.assertIn("word.format_review", js)
        self.assertNotIn("word.smart_format", js)
        for host_html_path, host_js_path in host_files:
            host_html = host_html_path.read_text(encoding="utf-8")
            host_js = host_js_path.read_text(encoding="utf-8")
            self.assertNotIn('id="provider-api-key"', host_html)
            self.assertNotIn('id="btn-save-api-key"', host_html)
            self.assertNotIn('id="btn-clear-api-key"', host_html)
            self.assertNotIn('request("/provider/api-key"', host_js)
        self.assertIn('path == "/provider/api-key"', standalone)
        self.assertIn("run/provider_api_key", installer)
        self.assertIn("run/provider_api_keys", installer)
        self.assertNotIn('id="btn-probe"', html)
        self.assertNotIn("runProbe", js)

    def test_smart_write_taskpane_uses_compact_prompt_controls(self) -> None:
        html = (ROOT / "formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html").read_text(
            encoding="utf-8"
        )
        js = (ROOT / "formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js").read_text(encoding="utf-8")

        self.assertIn("智能编写", html)
        self.assertIn('id="write-action"', html)
        self.assertIn('value="standard"', html)
        self.assertIn("技术方案正式", html)
        self.assertIn('id="rewrite-summary-card"', html)
        self.assertIn("rewrite-style-detail", html)
        self.assertIn("rewrite-focus-detail", html)
        self.assertIn("rewrite-length-detail", html)
        self.assertIn("rewrite-output-detail", html)
        self.assertIn("prompt-fragment-card", html)
        self.assertIn('id="prompt-fragment-card" class="prompt-fragment-card" hidden', html)
        self.assertIn("rewrite-prompt-label", html)
        self.assertIn("补充要求：请突出风险和下一步计划，压缩到200字以内。", html)
        self.assertIn("updateRewritePromptPreview", js)
        self.assertIn("showPromptFragments: false", js)
        self.assertIn('rewriteStyle: "standard"', js)
        self.assertIn('focusPoint: "complete"', js)
        self.assertIn('lengthMode: "same"', js)
        self.assertIn("prompt-fragment-card\").hidden = !shouldShowPromptFragments", js)
        self.assertIn("REWRITE_STYLE_PROMPTS", js)
        self.assertIn("不要原样返回待处理内容", js)
        self.assertIn("/word/smart-write", js)
        self.assertNotIn("/word/rewrite", js)

    def test_ribbon_uses_current_entries_and_current_icons(self) -> None:
        ribbon = (ROOT / "formal-plugin-kit/wps-ai-assistant_1.0.0/ribbon.xml").read_text(
            encoding="utf-8"
        )
        ribbon_js = (ROOT / "formal-plugin-kit/wps-ai-assistant_1.0.0/ribbon.js").read_text(
            encoding="utf-8"
        )

        for label in ["智能编写", "智能仿写", "文档审查", "格式审查", "设置"]:
            self.assertIn('label="{0}"'.format(label), ribbon)
        for old_label in ["格式校对", "智能排版", "技术文档审查"]:
            self.assertNotIn('label="{0}"'.format(old_label), ribbon)
        self.assertNotIn("智能改写", ribbon)
        self.assertNotIn("智能续写", ribbon)
        self.assertIn("btnAiSmartWrite", ribbon)
        self.assertIn("btnAiSmartImitation", ribbon)
        self.assertNotIn("btnAiRewrite", ribbon)
        self.assertNotIn("btnAiContinue", ribbon)
        self.assertIn("icon-smart-write.png", ribbon_js)
        self.assertIn("icon-smart-imitation.png", ribbon_js)
        self.assertIn("icon-review.png", ribbon_js)

    def test_phase1_publish_xml_contains_word_and_excel_addins(self) -> None:
        publish_xml = (ROOT / "phase1-delivery-kit/wps-jsaddons/publish.xml").read_text(
            encoding="utf-8"
        )

        self.assertIn('name="wps-ai-assistant"', publish_xml)
        self.assertIn('type="wps"', publish_xml)
        self.assertIn('name="wps-ai-assistant-et"', publish_xml)
        self.assertIn('type="et"', publish_xml)

    def test_excel_addin_contains_only_excel_ribbon_entries(self) -> None:
        ribbon = (ROOT / "formal-plugin-kit/wps-ai-assistant-et_1.0.0/ribbon.xml").read_text(
            encoding="utf-8"
        )
        ribbon_js = (ROOT / "formal-plugin-kit/wps-ai-assistant-et_1.0.0/ribbon.js").read_text(
            encoding="utf-8"
        )

        self.assertIn('label="智能分析"', ribbon)
        self.assertIn('label="设置"', ribbon)
        self.assertNotIn('label="智能编写"', ribbon)
        self.assertNotIn('label="智能仿写"', ribbon)
        self.assertNotIn('label="文档审查"', ribbon)
        self.assertNotIn('label="格式审查"', ribbon)
        self.assertIn("btnAiExcelAnalysis", ribbon_js)
        self.assertIn("icon-excel-analysis.png", ribbon_js)
