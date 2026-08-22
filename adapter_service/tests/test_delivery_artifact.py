import hashlib
import json
import ast
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ASSEMBLER = ROOT / "packaging/assemble_phase1_delivery.py"
AUDITOR = ROOT / "packaging/audit_phase1_delivery.py"
SOURCE_ALLOWLIST = ROOT / "packaging/delivery-sources-v0231.json"
SOURCE_ALLOWLIST_V0240 = ROOT / "packaging/delivery-sources-v0240.json"
LIFECYCLE_GATE = ROOT / "packaging/python38_delivery_lifecycle_gate.py"
V0240_BUILD = ROOT / "packaging/build_v0240_delivery_kit.sh"
V0251_BUILD = ROOT / "packaging/build_v0251_delivery_kit.sh"
V0251_PROVENANCE = ROOT / "packaging/check_delivery_source_provenance.py"


class DeliveryArtifactTests(unittest.TestCase):
    def test_source_allowlist_rejects_wildcard_tree_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "source").mkdir()
            (root / "source/app.py").write_text("pass\n", encoding="utf-8")
            policy = root / "policy.json"
            policy.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "version": "0.23.1-alpha",
                        "generatedFiles": ["release-file-hashes.json"],
                        "entries": [
                            {
                                "type": "tree",
                                "source": "source",
                                "target": "payload",
                                "include": ["*.py"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(ASSEMBLER),
                    "--repo-root",
                    str(root),
                    "--source-allowlist",
                    str(policy),
                    "--output",
                    str(root / "delivery"),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("ALLOWLIST_GLOB_REJECTED", result.stdout)

    def test_source_allowlist_rejects_symlinked_source_ancestors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo = root / "repo"
            outside = root / "outside"
            repo.mkdir()
            outside.mkdir()
            (outside / "payload.txt").write_text("outside\n", encoding="utf-8")
            (repo / "link").symlink_to(outside, target_is_directory=True)
            policy = repo / "policy.json"
            policy.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "version": "0.23.1-alpha",
                        "generatedFiles": ["release-file-hashes.json"],
                        "entries": [
                            {
                                "type": "file",
                                "source": "link/payload.txt",
                                "target": "payload.txt",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(ASSEMBLER),
                    "--repo-root",
                    str(repo),
                    "--source-allowlist",
                    str(policy),
                    "--output",
                    str(root / "delivery"),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("SOURCE_SYMLINK_REJECTED", result.stdout)

            (repo / "source").mkdir()
            (repo / "source/link").symlink_to(outside, target_is_directory=True)
            tree_policy = json.loads(policy.read_text(encoding="utf-8"))
            tree_policy["entries"] = [
                {
                    "type": "tree",
                    "source": "source",
                    "target": "payload",
                    "include": ["link/payload.txt"],
                }
            ]
            policy.write_text(json.dumps(tree_policy), encoding="utf-8")
            tree_result = subprocess.run(
                [
                    sys.executable,
                    str(ASSEMBLER),
                    "--repo-root",
                    str(repo),
                    "--source-allowlist",
                    str(policy),
                    "--output",
                    str(root / "tree-delivery"),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(tree_result.returncode, 0)
            self.assertIn("SOURCE_SYMLINK_REJECTED", tree_result.stdout)

    def test_explicit_allowlist_assembly_excludes_repository_only_content(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            delivery = Path(temp_dir) / "delivery"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ASSEMBLER),
                    "--repo-root",
                    str(ROOT),
                    "--source-allowlist",
                    str(SOURCE_ALLOWLIST_V0240),
                    "--output",
                    str(delivery),
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((delivery / "release-allowlist.json").is_file())
            release_allowlist = json.loads(
                (delivery / "release-allowlist.json").read_text(encoding="utf-8")
            )
            self.assertIn(
                "release-allowlist.json",
                release_allowlist["files"] + release_allowlist["generatedFiles"],
            )
            self.assertTrue(
                (
                    delivery
                    / "packages/adapter-start-kit/adapter_service/app/main.py"
                ).is_file()
            )
            self.assertTrue(
                (
                    delivery
                    / "packages/adapter-start-kit/adapter_service/tools/runtime_state.py"
                ).is_file()
            )
            for relative in (
                "packages/adapter-start-kit/adapter_service/system_prompts/word-document-review-full-chunk-correction.md",
                "packages/adapter-start-kit/adapter_service/system_prompts/word-document-review-full-aggregate.md",
                "packages/adapter-start-kit/adapter_service/system_prompts/word-document-review-full-aggregate-correction.md",
                "packages/adapter-start-kit/adapter_service/system_prompts/schemas/word-document-review-full-chunk.v2.json",
                "packages/adapter-start-kit/adapter_service/system_prompts/schemas/word-document-review-full-aggregate.v1.json",
            ):
                self.assertTrue((delivery / relative).is_file(), relative)

            names = {
                path.relative_to(delivery).as_posix()
                for path in delivery.rglob("*")
                if path.is_file()
            }
            forbidden_fragments = (
                "/tests/",
                "/__pycache__/",
                "/.pytest_cache/",
                "/standalone_adapter.py",
                "/tools/build_writing_policy_candidates.py",
                "/config/adapter.json",
                ".DS_Store",
            )
            self.assertFalse(
                [
                    name
                    for name in names
                    if any(fragment in "/" + name for fragment in forbidden_fragments)
                ]
            )

    def test_audit_rejects_unlisted_file_and_secret_then_verifies_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            delivery = Path(temp_dir) / "delivery"
            (delivery / "payload").mkdir(parents=True)
            (delivery / "scripts").mkdir()
            payload = delivery / "payload/app.py"
            payload.write_text("VERSION = '0.23.1-alpha'\n", encoding="utf-8")
            (delivery / "scripts/audit_delivery.py").write_text(
                "# delivery audit fixture\n", encoding="utf-8"
            )
            (delivery / "scripts/python38_delivery_lifecycle_gate.py").write_text(
                "# lifecycle gate fixture\n", encoding="utf-8"
            )
            (delivery / "prompts").mkdir()
            prompt = delivery / "prompts/system.md"
            prompt.write_text("safe prompt\n", encoding="utf-8")
            stage_prompt = delivery / "prompts/full-review-chunk.md"
            stage_prompt.write_text("strict stage prompt\n", encoding="utf-8")
            (delivery / "prompts/manifest.json").write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "release": "0.23.1-alpha",
                        "tasks": {
                            "word.smart_write": {
                                "file": "system.md",
                                "sha256": hashlib.sha256(prompt.read_bytes()).hexdigest(),
                            }
                        },
                        "stages": {
                            "word.document_review.full.chunk": {
                                "file": "full-review-chunk.md",
                                "sha256": hashlib.sha256(
                                    stage_prompt.read_bytes()
                                ).hexdigest(),
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            (delivery / "payload/settings.json").write_text(
                json.dumps({"apiKey": "placeholder"}), encoding="utf-8"
            )
            (delivery / "release-manifest.json").write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "version": "0.23.1-alpha",
                        "adapter": {
                            "version": "0.23.1-alpha",
                            "systemPromptManifest": "prompts/manifest.json",
                            "systemPromptCount": 1,
                        },
                        "deliveryPolicy": {
                            "status": "candidate",
                            "sourceAssembly": "explicit-allowlist",
                            "allowlist": "release-allowlist.json",
                            "fileHashes": "release-file-hashes.json",
                            "auditScript": "scripts/audit_delivery.py",
                            "lifecycleGate": "scripts/python38_delivery_lifecycle_gate.py",
                            "targetAcceptanceRequired": True,
                        },
                    }
                ),
                encoding="utf-8",
            )
            (delivery / "release-allowlist.json").write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "version": "0.23.1-alpha",
                        "files": [
                            "payload/app.py",
                            "payload/settings.json",
                            "prompts/manifest.json",
                            "prompts/full-review-chunk.md",
                            "prompts/system.md",
                            "release-manifest.json",
                            "scripts/audit_delivery.py",
                            "scripts/python38_delivery_lifecycle_gate.py",
                        ],
                        "generatedFiles": [
                            "release-allowlist.json",
                            "release-file-hashes.json",
                        ],
                    }
                ),
                encoding="utf-8",
            )

            first = subprocess.run(
                [sys.executable, str(AUDITOR), str(delivery), "--write-hashes"],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            hashes = json.loads(
                (delivery / "release-file-hashes.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                hashes["files"]["payload/app.py"],
                hashlib.sha256(payload.read_bytes()).hexdigest(),
            )

            prompt.write_text("tampered prompt\n", encoding="utf-8")
            prompt_tampered = subprocess.run(
                [sys.executable, str(AUDITOR), str(delivery), "--write-hashes"],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(prompt_tampered.returncode, 0)
            self.assertIn("PROMPT_HASH_MISMATCH", prompt_tampered.stdout)
            prompt.write_text("safe prompt\n", encoding="utf-8")

            stage_prompt.write_text("tampered stage prompt\n", encoding="utf-8")
            stage_prompt_tampered = subprocess.run(
                [sys.executable, str(AUDITOR), str(delivery), "--write-hashes"],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(stage_prompt_tampered.returncode, 0)
            self.assertIn("PROMPT_HASH_MISMATCH", stage_prompt_tampered.stdout)
            stage_prompt.write_text("strict stage prompt\n", encoding="utf-8")

            payload.write_text("VERSION = 'tampered'\n", encoding="utf-8")
            tampered = subprocess.run(
                [sys.executable, str(AUDITOR), str(delivery)],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(tampered.returncode, 0)
            self.assertIn("FILE_HASH_MISMATCH", tampered.stdout)

            payload.write_text("API_KEY = 'sk-live-secret-value-1234567890'\n", encoding="utf-8")
            secret = subprocess.run(
                [sys.executable, str(AUDITOR), str(delivery), "--write-hashes"],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(secret.returncode, 0)
            self.assertIn("SENSITIVE_VALUE_DETECTED", secret.stdout)

            payload.write_text("VERSION = '0.23.1-alpha'\n", encoding="utf-8")
            settings = delivery / "payload/settings.json"
            settings.write_text(
                json.dumps({"apiKey": "app-live-a1b2c3d4e5f6g7h8"}),
                encoding="utf-8",
            )
            json_secret = subprocess.run(
                [sys.executable, str(AUDITOR), str(delivery), "--write-hashes"],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(json_secret.returncode, 0)
            self.assertIn("SENSITIVE_VALUE_DETECTED", json_secret.stdout)
            settings.write_text(
                json.dumps({"apiKey": "placeholder"}), encoding="utf-8"
            )

            payload.write_text("VERSION = '0.23.1-alpha'\n", encoding="utf-8")
            (delivery / "payload/unlisted.txt").write_text("extra", encoding="utf-8")
            unlisted = subprocess.run(
                [sys.executable, str(AUDITOR), str(delivery), "--write-hashes"],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(unlisted.returncode, 0)
            self.assertIn("FILE_NOT_ALLOWLISTED", unlisted.stdout)

            (delivery / "payload/unlisted.txt").unlink()
            allowlist_path = delivery / "release-allowlist.json"
            allowlist = json.loads(allowlist_path.read_text(encoding="utf-8"))
            allowlist["generatedFiles"].append("generated-but-missing.md")
            allowlist_path.write_text(json.dumps(allowlist), encoding="utf-8")
            missing_generated = subprocess.run(
                [sys.executable, str(AUDITOR), str(delivery), "--write-hashes"],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(missing_generated.returncode, 0)
            self.assertIn("ALLOWLISTED_FILE_MISSING", missing_generated.stdout)

            allowlist["generatedFiles"].remove("generated-but-missing.md")
            allowlist_path.write_text(json.dumps(allowlist), encoding="utf-8")
            manifest_path = delivery / "release-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["deliveryPolicy"]["sourceAssembly"] = "recursive-copy"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            invalid_policy = subprocess.run(
                [sys.executable, str(AUDITOR), str(delivery), "--write-hashes"],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(invalid_policy.returncode, 0)
            self.assertIn("DELIVERY_POLICY_INVALID", invalid_policy.stdout)

            manifest["deliveryPolicy"]["sourceAssembly"] = "explicit-allowlist"
            manifest["operationsGuide"] = "../outside.txt"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            (delivery.parent / "outside.txt").write_text("outside\n", encoding="utf-8")
            escaping_reference = subprocess.run(
                [sys.executable, str(AUDITOR), str(delivery), "--write-hashes"],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(escaping_reference.returncode, 0)
            self.assertIn("REFERENCE_PATH_REJECTED", escaping_reference.stdout)

            manifest.pop("operationsGuide")
            external_plugin = delivery.parent / "external-plugin"
            external_plugin.mkdir()
            (external_plugin / "manifest.json").write_text(
                json.dumps({"version": "0.23.1-alpha"}), encoding="utf-8"
            )
            manifest["hosts"] = [{"plugin": str(external_plugin)}]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            escaping_plugin = subprocess.run(
                [sys.executable, str(AUDITOR), str(delivery), "--write-hashes"],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(escaping_plugin.returncode, 0)
            self.assertIn("PLUGIN_PATH_REJECTED", escaping_plugin.stdout)

    def test_installer_and_manifest_use_the_same_release_generation_components(self) -> None:
        manifest = json.loads(
            (ROOT / "phase1-delivery-kit/release-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        installer = (
            ROOT / "phase1-delivery-kit/installer/install_phase1.sh"
        ).read_text(encoding="utf-8")
        component_literals = re.findall(
            r'"components"\s*(?:\]|\))?\s*(?:==|:)\s*(\[[^]]+\])',
            installer,
            flags=re.DOTALL,
        )
        self.assertEqual(len(component_literals), 2)
        for literal in component_literals:
            self.assertEqual(
                ast.literal_eval(literal),
                manifest["releaseGenerationPolicy"]["components"],
            )
        self.assertEqual(installer.count('"runtime_state_snapshot",'), 2)
        self.assertIn("AI_WPS_TRANSACTION_FAIL_AFTER", installer)
        install_flow = installer.rsplit('log "phase1_install_start=true"', 1)[1]
        self.assertLess(
            install_flow.index('RELEASE_SWITCHED="1"'),
            install_flow.index("switch_release_generation"),
        )
        lifecycle = LIFECYCLE_GATE.read_text(encoding="utf-8")
        interruption = lifecycle.split("def run_interruption_fault", 1)[1].split(
            "def run_gate", 1
        )[0]
        self.assertIn("installer/install_phase1.sh", lifecycle)
        self.assertIn("after_switch:excel_plugin", interruption)
        for component in manifest["releaseGenerationPolicy"]["components"]:
            self.assertIn('"{0}"'.format(component), interruption)

    def test_build_runs_allowlist_audit_and_single_lifecycle_gate(self) -> None:
        build = (ROOT / "packaging/build_phase1_delivery_kit.sh").read_text(
            encoding="utf-8"
        )
        manifest = json.loads(
            (ROOT / "phase1-delivery-kit/release-manifest.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertIn("assemble_phase1_delivery.py", build)
        self.assertIn("audit_phase1_delivery.py", build)
        self.assertIn("python38_delivery_lifecycle_gate.py", build)
        self.assertNotIn('cp -R "$ROOT_DIR/phase1-delivery-kit/."', build)
        self.assertNotIn('cp -R "$ROOT_DIR/adapter_service"', build)
        self.assertNotIn('cp -R "$ADAPTER_SRC/."', build)
        self.assertEqual(
            manifest["deliveryPolicy"],
            {
                "status": "candidate",
                "sourceAssembly": "explicit-allowlist",
                "allowlist": "release-allowlist.json",
                "fileHashes": "release-file-hashes.json",
                "auditScript": "scripts/audit_delivery.py",
                "lifecycleGate": "scripts/python38_delivery_lifecycle_gate.py",
                "targetAcceptanceRequired": True,
            },
        )

    def test_lifecycle_gate_lists_all_required_scenarios_and_faults(self) -> None:
        result = subprocess.run(
            [sys.executable, str(LIFECYCLE_GATE), "--list"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(
            payload["scenarios"],
            [
                "fresh_install",
                "upgrade_v022",
                "upgrade_v0231",
                "damaged_v0230",
                "deleted_workflow_profile_overwrite",
            ],
        )
        self.assertEqual(
            payload["faults"],
            [
                "python_import_failure",
                "candidate_start_failure",
                "health_version_mismatch",
                "core_state_failure",
                "writing_policy_failure",
                "permission_error",
                "wps_not_exited",
                "install_interruption",
            ],
        )

    def test_v0251_build_records_only_the_complete_head_commit(self) -> None:
        build = V0251_BUILD.read_text(encoding="utf-8")

        self.assertIn('HEAD_COMMIT="$(git -C "$ROOT_DIR" rev-parse HEAD)"', build)
        self.assertIn('SOURCE_COMMIT="${AI_WPS_SOURCE_COMMIT:-$HEAD_COMMIT}"', build)
        self.assertIn("delivery_source_commit_not_head", build)
        self.assertIn("check_delivery_source_provenance.py", build)

    def test_v0251_source_provenance_rejects_dirty_allowlisted_input(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir) / "repo"
            packaging = repo / "packaging"
            packaging.mkdir(parents=True)
            build_inputs = (
                "assemble_phase1_delivery.py",
                "audit_phase1_delivery.py",
                "audit_v0251_delivery.py",
                "build_v0251_delivery_kit.sh",
                "check_delivery_source_provenance.py",
                "check_python38_compatibility.py",
                "prepare_v0251_delivery.py",
            )
            for name in build_inputs:
                (packaging / name).write_text(name + "\n", encoding="utf-8")
            rule_root = packaging / "format-rule-sources"
            rule_root.mkdir()
            for name in (
                "technical-document-template-rules.v1.0.0.json",
                "technical-document-template-rules.v1.0.0.structure.json",
            ):
                (rule_root / name).write_text(name + "\n", encoding="utf-8")
            node_tests = repo / "formal-plugin-kit/tests"
            node_tests.mkdir(parents=True)
            (node_tests / "tracked.test.js").write_text(
                "// tracked\n", encoding="utf-8"
            )
            (repo / "payload.txt").write_text("committed\n", encoding="utf-8")
            policy = packaging / "delivery-sources-v0251.json"
            policy.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "version": "0.25.1-alpha",
                        "generatedFiles": [],
                        "entries": [
                            {
                                "type": "file",
                                "source": "payload.txt",
                                "target": "payload.txt",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            commands = (
                ["git", "init", "-q"],
                ["git", "config", "user.email", "test@example.invalid"],
                ["git", "config", "user.name", "Delivery Test"],
                ["git", "add", "."],
                ["git", "commit", "-qm", "fixture"],
            )
            for command in commands:
                result = subprocess.run(
                    command, cwd=repo, check=False, capture_output=True, text=True
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            commit = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            command = [
                sys.executable,
                str(V0251_PROVENANCE),
                "--repo-root",
                str(repo),
                "--source-allowlist",
                str(policy),
                "--source-commit",
                commit,
            ]

            clean = subprocess.run(
                command, check=False, capture_output=True, text=True
            )
            self.assertEqual(clean.returncode, 0, clean.stdout + clean.stderr)
            (repo / "payload.txt").write_text("dirty\n", encoding="utf-8")
            dirty = subprocess.run(
                command, check=False, capture_output=True, text=True
            )

            self.assertNotEqual(dirty.returncode, 0)
            self.assertIn("DELIVERY_SOURCE_DIRTY payload.txt", dirty.stdout)
            (repo / "payload.txt").write_text("committed\n", encoding="utf-8")
            rule_path = (
                rule_root / "technical-document-template-rules.v1.0.0.json"
            )
            rule_path.write_text("dirty rule\n", encoding="utf-8")
            dirty_build_input = subprocess.run(
                command, check=False, capture_output=True, text=True
            )
            self.assertNotEqual(dirty_build_input.returncode, 0)
            self.assertIn(
                "technical-document-template-rules.v1.0.0.json",
                dirty_build_input.stdout,
            )
            subprocess.run(
                ["git", "checkout", "--", str(rule_path.relative_to(repo))],
                cwd=repo,
                check=True,
                capture_output=True,
                text=True,
            )
            (node_tests / "untracked.test.js").write_text(
                "// untracked\n", encoding="utf-8"
            )
            untracked_test = subprocess.run(
                command, check=False, capture_output=True, text=True
            )

        self.assertNotEqual(untracked_test.returncode, 0)
        self.assertIn(
            "DELIVERY_SOURCE_NOT_TRACKED formal-plugin-kit/tests/untracked.test.js",
            untracked_test.stdout,
        )

    def test_v0240_allowlist_and_build_are_explicit_candidate_inputs(self) -> None:
        policy = json.loads(SOURCE_ALLOWLIST_V0240.read_text(encoding="utf-8"))
        self.assertEqual(policy["version"], "0.24.0-alpha")
        self.assertEqual(policy["basePolicy"], "delivery-sources-v0231.json")
        serialized_entries = json.dumps(policy["entries"], ensure_ascii=False)
        for asset in (
            "word-document-review-full-chunk-correction.md",
            "word-document-review-full-aggregate.md",
            "word-document-review-full-aggregate-correction.md",
            "system_prompts/schemas",
        ):
            self.assertIn(asset, serialized_entries)

        build = V0240_BUILD.read_text(encoding="utf-8")
        self.assertIn("0.24.0-alpha", build)
        self.assertIn("delivery-sources-v0240.json", build)
        self.assertIn("python38_delivery_lifecycle_gate.py", build)
        self.assertIn("--baseline-archive", build)
        self.assertIn("status=candidate", build)

    def test_v0240_preparation_preserves_previous_candidate_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "release-manifest.json").write_text(
                json.dumps(
                    {
                        "version": "0.23.1-alpha",
                        "adapter": {
                            "version": "0.23.1-alpha",
                            "systemPromptManifest": "prompts/manifest.json",
                        },
                        "deliveryPolicy": {"status": "candidate"},
                    }
                ),
                encoding="utf-8",
            )
            (root / "release-allowlist.json").write_text(
                json.dumps({"version": "0.23.1-alpha"}), encoding="utf-8"
            )
            (root / "packages").mkdir()
            (root / "prompts").mkdir()
            (root / "prompts/manifest.json").write_text(
                json.dumps({"release": "0.23.1-alpha"}), encoding="utf-8"
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "packaging/prepare_v0240_delivery.py"),
                    str(root),
                    "--date",
                    "20260812",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            manifest = json.loads((root / "release-manifest.json").read_text())
            self.assertEqual(manifest["version"], "0.24.0-alpha")
            self.assertEqual(manifest["baseline"]["previousCandidate"], "0.23.1-alpha")


if __name__ == "__main__":
    unittest.main()
