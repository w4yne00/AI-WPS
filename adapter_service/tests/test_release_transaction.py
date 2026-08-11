import hashlib
import json
import os
import pwd
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TRANSACTION_SCRIPT = (
    ROOT / "phase1-delivery-kit/installer/release_transaction.py"
)


class ReleaseTransactionTests(unittest.TestCase):
    def _write_snapshot(
        self,
        backup_dir: Path,
        snapshot_id: str,
        release_version: str,
        state_source: Path,
    ) -> None:
        snapshot_dir = backup_dir / snapshot_id
        snapshot_dir.mkdir(parents=True)
        snapshot_state = snapshot_dir / "state"
        shutil.copytree(str(state_source), str(snapshot_state))
        files = [
            {
                "path": path.relative_to(snapshot_state).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "size": path.stat().st_size,
            }
            for path in sorted(snapshot_state.rglob("*"))
            if path.is_file()
        ]
        (snapshot_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "snapshotId": snapshot_id,
                    "releaseVersion": release_version,
                    "valid": True,
                    "files": files,
                }
            ),
            encoding="utf-8",
        )

    def _prepare_generation(self, root: Path):
        install_root = root / "install"
        releases = install_root / "releases"
        jsaddons = root / "jsaddons"
        transactions = install_root / "var" / "transactions"
        backups = install_root / "backups"
        releases.mkdir(parents=True)
        jsaddons.mkdir()
        transactions.mkdir(parents=True)
        backups.mkdir()

        release_version = "0.23.1-alpha"
        release_target = releases / release_version
        release_candidate = releases / ".0.23.1-alpha.candidate"
        release_target.mkdir()
        release_candidate.mkdir()
        (release_target / "version.txt").write_text("old", encoding="utf-8")
        (release_candidate / "version.txt").write_text("new", encoding="utf-8")

        components = [("adapter_release", release_candidate, release_target)]
        for name in ("word", "excel", "ppt"):
            target = jsaddons / (name + "-plugin")
            candidate = jsaddons / ("." + name + "-candidate")
            target.mkdir()
            candidate.mkdir()
            (target / "version.txt").write_text("old", encoding="utf-8")
            (candidate / "version.txt").write_text("new", encoding="utf-8")
            components.append((name + "_plugin", candidate, target))

        publish_target = jsaddons / "publish.xml"
        publish_candidate = jsaddons / ".publish.candidate.xml"
        publish_target.write_text("old-publish", encoding="utf-8")
        publish_candidate.write_text("new-publish", encoding="utf-8")
        components.append(("publish_manifest", publish_candidate, publish_target))

        state_target = install_root / "state"
        state_candidate = install_root / ".state.candidate"
        state_target.mkdir()
        state_candidate.mkdir()
        (state_target / "version.txt").write_text("old", encoding="utf-8")
        (state_candidate / "version.txt").write_text("new", encoding="utf-8")
        components.append(
            ("runtime_state_snapshot", state_candidate, state_target)
        )

        current_target = install_root / "current"
        current_candidate = install_root / ".current.candidate"
        os.symlink(str(release_target), str(current_candidate))
        components.append(("current_pointer", current_candidate, current_target))

        candidate_snapshot_id = "snapshot-new-generation"
        self._write_snapshot(
            backups,
            candidate_snapshot_id,
            release_version,
            state_candidate,
        )
        return {
            "backups": backups,
            "candidate_snapshot_id": candidate_snapshot_id,
            "components": components,
            "current": current_target,
            "release_target": release_target,
            "release_version": release_version,
            "state": state_target,
            "transactions": transactions,
        }

    def _run(self, *arguments: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(TRANSACTION_SCRIPT), *arguments],
            check=False,
            capture_output=True,
            text=True,
        )

    def _prepare_transaction(self, paths, transaction_id: str) -> Path:
        arguments = [
            "prepare",
            "--transaction-dir",
            str(paths["transactions"]),
            "--transaction-id",
            transaction_id,
            "--release-version",
            paths["release_version"],
            "--backup-dir",
            str(paths["backups"]),
            "--candidate-snapshot-id",
            paths["candidate_snapshot_id"],
        ]
        for name, candidate, target in paths["components"]:
            arguments.extend(["--component", name, str(candidate), str(target)])
        prepared = self._run(*arguments)
        self.assertEqual(prepared.returncode, 0, prepared.stderr or prepared.stdout)
        return paths["transactions"] / (transaction_id + ".json")

    def test_commit_switches_all_components_as_one_generation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = self._prepare_generation(Path(temp_dir))
            transaction_log = self._prepare_transaction(paths, "txn-commit")

            switched = self._run("switch", str(transaction_log))
            self.assertEqual(switched.returncode, 0, switched.stderr or switched.stdout)
            finalized = self._run("finalize", str(transaction_log))
            self.assertEqual(finalized.returncode, 0, finalized.stderr or finalized.stdout)

            for unused_name, unused_candidate, target in paths["components"][:-1]:
                expected = "new-publish" if target.name == "publish.xml" else "new"
                source = target if target.is_file() else target / "version.txt"
                self.assertEqual(source.read_text(encoding="utf-8"), expected)
            self.assertTrue(paths["current"].is_symlink())
            self.assertTrue(paths["current"].samefile(paths["release_target"]))
            transaction = json.loads(
                transaction_log.read_text(encoding="utf-8")
            )
            self.assertEqual(transaction["status"], "committed")
            self.assertEqual(
                transaction["candidateSnapshotId"],
                paths["candidate_snapshot_id"],
            )
            self.assertTrue(all(item["verified"] for item in transaction["components"]))

    def test_each_interrupted_switch_phase_recovers_the_previous_generation(self) -> None:
        component_names = [
            "adapter_release",
            "word_plugin",
            "excel_plugin",
            "ppt_plugin",
            "publish_manifest",
            "runtime_state_snapshot",
            "current_pointer",
        ]
        failpoints = [
            "{0}:{1}".format(phase, name)
            for name in component_names
            for phase in ("after_backup", "after_switch")
        ]
        for failpoint in failpoints:
            with self.subTest(failpoint=failpoint):
                with tempfile.TemporaryDirectory() as temp_dir:
                    paths = self._prepare_generation(Path(temp_dir))
                    transaction_log = self._prepare_transaction(paths, "txn-interrupt")

                    interrupted = self._run(
                        "switch", str(transaction_log), "--fail-after", failpoint
                    )
                    self.assertEqual(
                        interrupted.returncode,
                        97,
                        interrupted.stderr or interrupted.stdout,
                    )
                    recovered = self._run("recover", str(transaction_log))
                    self.assertEqual(
                        recovered.returncode,
                        0,
                        recovered.stderr or recovered.stdout,
                    )

                    for unused_name, unused_candidate, target in paths["components"][:-1]:
                        expected = "old-publish" if target.name == "publish.xml" else "old"
                        source = target if target.is_file() else target / "version.txt"
                        self.assertEqual(source.read_text(encoding="utf-8"), expected)
                    self.assertFalse(os.path.lexists(str(paths["current"])))
                    transaction = json.loads(
                        transaction_log.read_text(encoding="utf-8")
                    )
                    self.assertEqual(transaction["status"], "rolled_back")

    def test_rollback_restores_the_runtime_state_matching_the_previous_generation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = self._prepare_generation(Path(temp_dir))
            (paths["state"] / "degraded-policy.db").write_bytes(b"old-invalid")
            transaction_log = self._prepare_transaction(paths, "txn-state-restore")
            switched = self._run("switch", str(transaction_log))
            self.assertEqual(switched.returncode, 0, switched.stderr or switched.stdout)

            rolled_back = self._run("rollback", str(transaction_log))
            self.assertEqual(
                rolled_back.returncode,
                0,
                rolled_back.stderr or rolled_back.stdout,
            )
            self.assertEqual(
                (paths["state"] / "version.txt").read_text(encoding="utf-8"),
                "old",
            )
            self.assertEqual(
                (paths["state"] / "degraded-policy.db").read_bytes(),
                b"old-invalid",
            )
            transaction = json.loads(transaction_log.read_text(encoding="utf-8"))
            self.assertEqual(transaction["status"], "rolled_back")

    def test_candidate_snapshot_tampering_blocks_commit_and_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = self._prepare_generation(Path(temp_dir))
            transaction_log = self._prepare_transaction(paths, "txn-snapshot-tamper")
            switched = self._run("switch", str(transaction_log))
            self.assertEqual(switched.returncode, 0, switched.stderr or switched.stdout)
            snapshot_manifest = (
                paths["backups"]
                / paths["candidate_snapshot_id"]
                / "manifest.json"
            )
            snapshot_manifest.write_text("{}\n", encoding="utf-8")

            finalized = self._run("finalize", str(transaction_log))

            self.assertNotEqual(finalized.returncode, 0)
            transaction = json.loads(transaction_log.read_text(encoding="utf-8"))
            self.assertEqual(transaction["status"], "verification_failed")
            recovered = self._run("recover", str(transaction_log))
            self.assertEqual(recovered.returncode, 0, recovered.stderr or recovered.stdout)
            self.assertEqual(
                (paths["state"] / "version.txt").read_text(encoding="utf-8"),
                "old",
            )

    def test_deferred_finalization_remains_recoverable_until_external_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = self._prepare_generation(Path(temp_dir))
            transaction_log = self._prepare_transaction(paths, "txn-deferred")
            switched = self._run("switch", str(transaction_log))
            self.assertEqual(switched.returncode, 0, switched.stderr or switched.stdout)

            finalized = self._run(
                "finalize", str(transaction_log), "--defer-commit"
            )

            self.assertEqual(finalized.returncode, 0, finalized.stderr or finalized.stdout)
            transaction = json.loads(transaction_log.read_text(encoding="utf-8"))
            self.assertEqual(transaction["status"], "ready_to_commit")
            self.assertTrue(
                all(Path(item["backup"]).exists() for item in transaction["components"][:-1])
            )
            recovered = self._run("recover", str(transaction_log))
            self.assertEqual(recovered.returncode, 0, recovered.stderr or recovered.stdout)
            self.assertEqual(
                (paths["state"] / "version.txt").read_text(encoding="utf-8"),
                "old",
            )

    def test_external_commit_reverifies_and_commits_deferred_generation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = self._prepare_generation(Path(temp_dir))
            transaction_log = self._prepare_transaction(paths, "txn-external-commit")
            self.assertEqual(self._run("switch", str(transaction_log)).returncode, 0)
            self.assertEqual(
                self._run(
                    "finalize", str(transaction_log), "--defer-commit"
                ).returncode,
                0,
            )

            committed = self._run("commit", str(transaction_log))

            self.assertEqual(committed.returncode, 0, committed.stderr or committed.stdout)
            transaction = json.loads(transaction_log.read_text(encoding="utf-8"))
            self.assertEqual(transaction["status"], "committed")
            self.assertTrue(all(item["verified"] for item in transaction["components"]))
            self.assertEqual(
                (paths["state"] / "version.txt").read_text(encoding="utf-8"),
                "new",
            )

    def test_external_commit_failure_keeps_compensation_available(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = self._prepare_generation(Path(temp_dir))
            transaction_log = self._prepare_transaction(paths, "txn-external-failure")
            self.assertEqual(self._run("switch", str(transaction_log)).returncode, 0)
            self.assertEqual(
                self._run(
                    "finalize", str(transaction_log), "--defer-commit"
                ).returncode,
                0,
            )
            (paths["state"] / "version.txt").write_text(
                "mutated-after-systemd-start", encoding="utf-8"
            )

            committed = self._run("commit", str(transaction_log))

            self.assertNotEqual(committed.returncode, 0)
            transaction = json.loads(transaction_log.read_text(encoding="utf-8"))
            self.assertEqual(transaction["status"], "verification_failed")
            recovered = self._run("recover", str(transaction_log))
            self.assertEqual(recovered.returncode, 0, recovered.stderr or recovered.stdout)
            self.assertEqual(
                (paths["state"] / "version.txt").read_text(encoding="utf-8"),
                "old",
            )

    def test_mixed_generation_fails_finalization_and_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = self._prepare_generation(Path(temp_dir))
            transaction_log = self._prepare_transaction(paths, "txn-mixed")
            switched = self._run("switch", str(transaction_log))
            self.assertEqual(switched.returncode, 0, switched.stderr or switched.stdout)
            word_target = next(
                target
                for name, unused_candidate, target in paths["components"]
                if name == "word_plugin"
            )
            (word_target / "version.txt").write_text(
                "mixed-generation", encoding="utf-8"
            )

            finalized = self._run("finalize", str(transaction_log))
            self.assertNotEqual(finalized.returncode, 0)
            transaction = json.loads(transaction_log.read_text(encoding="utf-8"))
            self.assertEqual(transaction["status"], "verification_failed")
            self.assertFalse(all(item["verified"] for item in transaction["components"]))

            recovered = self._run("recover", str(transaction_log))
            self.assertEqual(recovered.returncode, 0, recovered.stderr or recovered.stdout)
            for unused_name, unused_candidate, target in paths["components"][:-1]:
                expected = "old-publish" if target.name == "publish.xml" else "old"
                source = target if target.is_file() else target / "version.txt"
                self.assertEqual(source.read_text(encoding="utf-8"), expected)
            self.assertFalse(os.path.lexists(str(paths["current"])))

    def test_phase1_installer_commits_and_compensates_complete_generations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            delivery = root / "delivery"
            installer_dir = delivery / "installer"
            packages = delivery / "packages"
            jsaddons = root / "jsaddons"
            install_root = root / "install"
            installer_dir.mkdir(parents=True)
            packages.mkdir()
            jsaddons.mkdir()
            install_root.mkdir()
            bin_dir = root / "bin"
            bin_dir.mkdir()
            ps_stub = bin_dir / "ps"
            ps_stub.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            ps_stub.chmod(0o755)

            shutil.copy2(
                ROOT / "phase1-delivery-kit/installer/install_phase1.sh",
                installer_dir / "install_phase1.sh",
            )
            shutil.copy2(
                TRANSACTION_SCRIPT, installer_dir / "release_transaction.py"
            )
            for plugin_name in (
                "wps-ai-assistant_1.0.0",
                "wps-ai-assistant-et_1.0.0",
                "wps-ai-assistant-wpp_1.0.0",
            ):
                plugin = packages / plugin_name
                plugin.mkdir()
                (plugin / "version.txt").write_text("candidate", encoding="utf-8")
                (plugin / "manifest.json").write_text(
                    json.dumps(
                        {
                            "name": plugin_name.rsplit("_", 1)[0],
                            "version": "0.23.1-alpha",
                        }
                    ),
                    encoding="utf-8",
                )

            adapter = packages / "adapter-start-kit"
            (adapter / "version.txt").parent.mkdir(parents=True, exist_ok=True)
            (adapter / "version.txt").write_text("generation-one", encoding="utf-8")
            scripts = adapter / "scripts"
            state_tools = adapter / "adapter_service" / "tools"
            scripts.mkdir(parents=True)
            state_tools.mkdir(parents=True)
            for script_name, body in {
                "stop_adapter.sh": "#!/usr/bin/env bash\nif [ -n \"${FAIL_STOP_MARKER:-}\" ] && [ -f \"$FAIL_STOP_MARKER\" ]; then exit 12; fi\nexit 0\n",
                "start_uvicorn_adapter.sh": "#!/usr/bin/env bash\nKIT_ROOT=\"$(cd \"$(dirname \"${BASH_SOURCE[0]}\")/..\" && pwd)\"\ncat \"$KIT_ROOT/version.txt\" >> \"$ADAPTER_START_LOG\"\nprintf '\\n' >> \"$ADAPTER_START_LOG\"\n",
                "check_health.sh": "#!/usr/bin/env bash\nexit 0\n",
            }.items():
                script = scripts / script_name
                script.write_text(body, encoding="utf-8")
                script.chmod(0o755)
            shutil.copy2(
                ROOT / "adapter-start-kit/scripts/systemd_unit.sh",
                scripts / "systemd_unit.sh",
            )
            runtime_tool = state_tools / "runtime_state.py"
            runtime_tool.write_text(
                """#!/usr/bin/env python3
import argparse, hashlib, json, os, shutil, uuid
from pathlib import Path
p=argparse.ArgumentParser(); p.add_argument('command'); p.add_argument('--state-dir'); p.add_argument('--backup-dir'); p.add_argument('--release-version'); p.add_argument('--reason'); p.add_argument('--legacy-root'); p.add_argument('--snapshot-id'); p.add_argument('--confirm'); a=p.parse_args()
if a.command == 'restore':
    source=Path(a.backup_dir)/a.snapshot_id/'state'; state=Path(a.state_dir)
    if state.exists(): shutil.rmtree(str(state))
    shutil.copytree(str(source), str(state))
    print(json.dumps({'success':True,'status':'ready','snapshotId':a.snapshot_id}))
else:
    snapshot_id='snapshot-' + (a.reason or 'migration').replace('_','-') + '-' + uuid.uuid4().hex[:8]
    source=Path(a.state_dir); target=Path(a.backup_dir)/snapshot_id; target.mkdir(parents=True)
    shutil.copytree(str(source), str(target/'state'))
    degraded=(source/'writing_policies.db').exists() and (source/'writing_policies.db').read_bytes() == b'existing-policy'
    status=os.environ.get('FAKE_RUNTIME_STATUS') or ('degraded' if degraded else 'ready')
    files=[{'path':p.relative_to(source).as_posix(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'size':p.stat().st_size} for p in sorted(source.rglob('*')) if p.is_file()]
    (target/'manifest.json').write_text(json.dumps({'schemaVersion':1,'snapshotId':snapshot_id,'releaseVersion':a.release_version,'valid':not degraded,'coreStatus':'ready','writingPolicyStatus':'degraded' if degraded else 'ready','files':files}), encoding='utf-8')
    print(json.dumps({'success':True,'status':status,'snapshotId':snapshot_id,'valid':not degraded}))
""",
                encoding="utf-8",
            )
            runtime_tool.chmod(0o755)

            for script_name, body in {
                "install_private_runtime.sh": "#!/usr/bin/env bash\nmkdir -p \"$4\"\n",
                "preflight_candidate.sh": "#!/usr/bin/env bash\nexit 0\n",
            }.items():
                script = installer_dir / script_name
                script.write_text(body, encoding="utf-8")
                script.chmod(0o755)
            (packages / "kylin-v10-arm-py38").mkdir()
            (packages / "kylin-v10-arm-py38-pip-bootstrap").mkdir()
            (delivery / "wps-jsaddons").mkdir()
            (delivery / "wps-jsaddons" / "publish.xml").write_text(
                """<jsplugins>
<jsplugin name="wps-ai-assistant" type="wps" version="1.0.0"/>
<jsplugin name="wps-ai-assistant-et" type="et" version="1.0.0"/>
<jsplugin name="wps-ai-assistant-wpp" type="wpp" version="1.0.0"/>
</jsplugins>
""",
                encoding="utf-8",
            )
            (delivery / "release-manifest.json").write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "version": "0.23.1-alpha",
                        "adapter": {"version": "0.23.1-alpha"},
                        "hosts": [
                            {
                                "name": "Word",
                                "plugin": "wps-ai-assistant_1.0.0",
                                "ribbonType": "wps",
                            },
                            {
                                "name": "Excel",
                                "plugin": "wps-ai-assistant-et_1.0.0",
                                "ribbonType": "et",
                            },
                            {
                                "name": "PPT",
                                "plugin": "wps-ai-assistant-wpp_1.0.0",
                                "ribbonType": "wpp",
                            },
                        ],
                        "releaseGenerationPolicy": {
                            "switchStrategy": "durable-compensating-rename",
                            "currentPointer": "current",
                            "components": [
                                "adapter_release",
                                "word_plugin",
                                "excel_plugin",
                                "ppt_plugin",
                                "publish_manifest",
                                "runtime_state_snapshot",
                                "current_pointer",
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )
            state_dir = install_root / "state"
            state_dir.mkdir()
            (state_dir / "adapter.json").write_text("{}\n", encoding="utf-8")
            (state_dir / "writing_policies.db").write_bytes(b"existing-policy")

            environment = dict(os.environ)
            environment.pop("SUDO_USER", None)
            environment.pop("SUDO_UID", None)
            environment.pop("AI_WPS_STATE_DIR", None)
            environment.pop("AI_WPS_BACKUP_DIR", None)
            environment.pop("AI_WPS_VAR_DIR", None)
            environment.update(
                {
                    "AI_WPS_INSTALL_ROOT": str(install_root),
                    "WPS_JSADDONS_DIR": str(jsaddons),
                    "PYTHON_BIN": sys.executable,
                    "PORT": "28123",
                    "ADAPTER_START_LOG": str(root / "adapter-start.log"),
                    "PATH": "{0}:{1}".format(
                        bin_dir, environment.get("PATH", "")
                    ),
                }
            )
            result = subprocess.run(
                ["bash", str(installer_dir / "install_phase1.sh")],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )

            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            current = install_root / "current"
            release = install_root / "releases" / "0.23.1-alpha"
            self.assertTrue(current.is_symlink())
            self.assertTrue(current.samefile(release))
            self.assertTrue((release / "python-runtime").is_dir())
            self.assertTrue((release / "release-manifest.json").is_file())
            for plugin_name in (
                "wps-ai-assistant_1.0.0",
                "wps-ai-assistant-et_1.0.0",
                "wps-ai-assistant-wpp_1.0.0",
            ):
                self.assertEqual(
                    (jsaddons / plugin_name / "version.txt").read_text(
                        encoding="utf-8"
                    ),
                    "candidate",
                )
            transactions = list((install_root / "var" / "transactions").glob("*.json"))
            self.assertEqual(len(transactions), 1)
            transaction = json.loads(transactions[0].read_text(encoding="utf-8"))
            self.assertEqual(transaction["status"], "committed")
            self.assertEqual(
                [item["name"] for item in transaction["components"]],
                [
                    "adapter_release",
                    "word_plugin",
                    "excel_plugin",
                    "ppt_plugin",
                    "publish_manifest",
                    "runtime_state_snapshot",
                    "current_pointer",
                ],
            )

            for plugin_name in (
                "wps-ai-assistant_1.0.0",
                "wps-ai-assistant-et_1.0.0",
                "wps-ai-assistant-wpp_1.0.0",
            ):
                (packages / plugin_name / "version.txt").write_text(
                    "candidate-two", encoding="utf-8"
                )
            (adapter / "version.txt").write_text(
                "generation-two", encoding="utf-8"
            )
            (scripts / "check_health.sh").write_text(
                "#!/usr/bin/env bash\nexit 1\n", encoding="utf-8"
            )
            failed_upgrade = subprocess.run(
                ["bash", str(installer_dir / "install_phase1.sh")],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )

            self.assertNotEqual(failed_upgrade.returncode, 0)
            self.assertTrue(current.samefile(release))
            self.assertEqual(
                (release / "version.txt").read_text(encoding="utf-8"),
                "generation-one",
            )
            self.assertEqual(
                json.loads((state_dir / "adapter.json").read_text(encoding="utf-8")),
                {},
            )
            for plugin_name in (
                "wps-ai-assistant_1.0.0",
                "wps-ai-assistant-et_1.0.0",
                "wps-ai-assistant-wpp_1.0.0",
            ):
                self.assertEqual(
                    (jsaddons / plugin_name / "version.txt").read_text(
                        encoding="utf-8"
                    ),
                    "candidate",
                )
            statuses = sorted(
                json.loads(path.read_text(encoding="utf-8"))["status"]
                for path in (install_root / "var" / "transactions").glob("*.json")
            )
            self.assertEqual(statuses, ["committed", "rolled_back"])
            self.assertEqual(
                (root / "adapter-start.log").read_text(encoding="utf-8").splitlines(),
                ["generation-one", "generation-two", "generation-one"],
            )

            (scripts / "check_health.sh").write_text(
                "#!/usr/bin/env bash\nexit 0\n", encoding="utf-8"
            )
            word_manifest = packages / "wps-ai-assistant_1.0.0" / "manifest.json"
            invalid_word = json.loads(word_manifest.read_text(encoding="utf-8"))
            invalid_word["version"] = "wrong-generation"
            word_manifest.write_text(json.dumps(invalid_word), encoding="utf-8")
            transaction_count = len(
                list((install_root / "var" / "transactions").glob("*.json"))
            )

            invalid_plugin_upgrade = subprocess.run(
                ["bash", str(installer_dir / "install_phase1.sh")],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )

            self.assertNotEqual(invalid_plugin_upgrade.returncode, 0)
            self.assertIn(
                "candidate_plugin_generation_invalid",
                invalid_plugin_upgrade.stdout,
            )
            self.assertTrue(current.samefile(release))
            self.assertEqual(
                len(list((install_root / "var" / "transactions").glob("*.json"))),
                transaction_count,
            )

            invalid_word["version"] = "0.23.1-alpha"
            word_manifest.write_text(json.dumps(invalid_word), encoding="utf-8")
            unknown_status_environment = dict(environment)
            unknown_status_environment["FAKE_RUNTIME_STATUS"] = "unknown"

            unknown_state_upgrade = subprocess.run(
                ["bash", str(installer_dir / "install_phase1.sh")],
                check=False,
                capture_output=True,
                text=True,
                env=unknown_status_environment,
            )

            self.assertNotEqual(unknown_state_upgrade.returncode, 0)
            self.assertIn(
                "runtime_state_snapshot_status=invalid value=unknown",
                unknown_state_upgrade.stdout,
            )
            self.assertTrue(current.samefile(release))

            actual_uid = os.getuid()
            actual_user = pwd.getpwuid(actual_uid).pw_name
            actual_home = pwd.getpwuid(actual_uid).pw_dir
            real_id = shutil.which("id")
            self.assertIsNotNone(real_id)
            (bin_dir / "id").write_text(
                """#!/usr/bin/env bash
if [ "${{FAKE_TARGET_CHILD:-0}}" = "1" ]; then exec "{real_id}" "$@"; fi
case "$1" in
  -u)
    if [ "$#" -gt 1 ]; then exec "{real_id}" "$@"; fi
    printf '%s\n' 0
    ;;
  -un) printf '%s\n' root ;;
  *) exec "{real_id}" "$@" ;;
esac
""".format(real_id=real_id),
                encoding="utf-8",
            )
            (bin_dir / "runuser").write_text(
                """#!/usr/bin/env bash
shift 3
export FAKE_TARGET_CHILD=1
exec "$@"
""",
                encoding="utf-8",
            )
            (bin_dir / "getent").write_text(
                """#!/usr/bin/env bash
printf '%s\n' '{user}:x:{uid}:20::{home}:/bin/bash'
""".format(user=actual_user, uid=actual_uid, home=actual_home),
                encoding="utf-8",
            )
            (bin_dir / "systemctl").write_text(
                """#!/usr/bin/env bash
case "$1" in
  is-active) grep -q '^active$' "$SYSTEMD_STATE_FILE" ;;
  stop) printf '%s\n' inactive > "$SYSTEMD_STATE_FILE" ;;
  daemon-reload) exit 0 ;;
  start)
    if [ "${SYSTEMD_START_INTERRUPT:-0}" = "1" ]; then
      kill -9 "$PPID"
      exit 137
    fi
    if [ "${SYSTEMD_BREAK_COMPENSATION:-0}" = "1" ]; then
      touch "$FAIL_STOP_MARKER"
      exit 9
    fi
    if [ "${SYSTEMD_START_FAIL:-0}" = "1" ]; then exit 9; fi
    printf '%s\n' active > "$SYSTEMD_STATE_FILE"
    ;;
  *) exit 0 ;;
esac
""",
                encoding="utf-8",
            )
            for command in ("id", "runuser", "getent", "systemctl"):
                (bin_dir / command).chmod(0o755)
            service_file = root / "ai-wps-adapter.service"
            service_file.write_text("old-unit\n", encoding="utf-8")
            systemd_state = root / "systemd-state"
            systemd_state.write_text("active\n", encoding="utf-8")
            systemd_environment = dict(environment)
            systemd_environment.update(
                {
                    "AI_WPS_SYSTEMD_SERVICE_FILE": str(service_file),
                    "FAKE_TARGET_HOME": actual_home,
                    "SYSTEMD_STATE_FILE": str(systemd_state),
                }
            )
            (adapter / "version.txt").write_text(
                "generation-systemd", encoding="utf-8"
            )
            for plugin_name in (
                "wps-ai-assistant_1.0.0",
                "wps-ai-assistant-et_1.0.0",
                "wps-ai-assistant-wpp_1.0.0",
            ):
                (packages / plugin_name / "version.txt").write_text(
                    "candidate-systemd", encoding="utf-8"
                )
            admin_arguments = [
                "bash",
                str(installer_dir / "install_phase1.sh"),
                "--target-user",
                actual_user,
                "--target-uid",
                str(actual_uid),
                "--target-home",
                actual_home,
                "--wps-jsaddons-dir",
                str(jsaddons),
            ]

            systemd_upgrade = subprocess.run(
                admin_arguments,
                check=False,
                capture_output=True,
                text=True,
                env=systemd_environment,
            )

            self.assertEqual(
                systemd_upgrade.returncode,
                0,
                systemd_upgrade.stderr or systemd_upgrade.stdout,
            )
            stable_unit = service_file.read_text(encoding="utf-8")
            self.assertIn('WorkingDirectory="{0}"'.format(current), stable_unit)
            self.assertEqual(
                systemd_state.read_text(encoding="utf-8"),
                "active\n",
                systemd_upgrade.stderr or systemd_upgrade.stdout,
            )
            self.assertFalse((service_file.parent / (service_file.name + ".ai-wps.previous")).exists())
            latest_transaction = max(
                (install_root / "var" / "transactions").glob("*.json"),
                key=lambda path: path.stat().st_mtime_ns,
            )
            self.assertEqual(
                json.loads(latest_transaction.read_text(encoding="utf-8"))["status"],
                "committed",
            )

            (adapter / "version.txt").write_text(
                "generation-systemd-failure", encoding="utf-8"
            )
            failing_systemd_environment = dict(systemd_environment)
            failing_systemd_environment["SYSTEMD_START_FAIL"] = "1"
            failed_systemd_upgrade = subprocess.run(
                admin_arguments,
                check=False,
                capture_output=True,
                text=True,
                env=failing_systemd_environment,
            )

            self.assertNotEqual(failed_systemd_upgrade.returncode, 0)
            self.assertEqual(service_file.read_text(encoding="utf-8"), stable_unit)
            self.assertEqual(
                (release / "version.txt").read_text(encoding="utf-8"),
                "generation-systemd",
            )
            latest_transaction = max(
                (install_root / "var" / "transactions").glob("*.json"),
                key=lambda path: path.stat().st_mtime_ns,
            )
            self.assertEqual(
                json.loads(latest_transaction.read_text(encoding="utf-8"))["status"],
                "rolled_back",
            )

            retry_failed_start_environment = dict(systemd_environment)
            retry_failed_start_environment["FAKE_RUNTIME_STATUS"] = "unknown"
            retry_failed_start = subprocess.run(
                admin_arguments,
                check=False,
                capture_output=True,
                text=True,
                env=retry_failed_start_environment,
            )
            self.assertNotEqual(retry_failed_start.returncode, 0)
            self.assertEqual(systemd_state.read_text(encoding="utf-8"), "active\n")
            self.assertFalse(
                (install_root / "var" / "run" / "systemd-release-handoff.json").exists()
            )

            stop_failure_marker = root / "candidate-stop-failed"
            (adapter / "version.txt").write_text(
                "generation-systemd-compensation-retry", encoding="utf-8"
            )
            incomplete_compensation_environment = dict(systemd_environment)
            incomplete_compensation_environment.update(
                {
                    "FAIL_STOP_MARKER": str(stop_failure_marker),
                    "SYSTEMD_BREAK_COMPENSATION": "1",
                }
            )
            incomplete_compensation = subprocess.run(
                admin_arguments,
                check=False,
                capture_output=True,
                text=True,
                env=incomplete_compensation_environment,
            )

            self.assertNotEqual(incomplete_compensation.returncode, 0)
            handoff = install_root / "var" / "run" / "systemd-release-handoff.json"
            unit_backup = service_file.parent / (service_file.name + ".ai-wps.previous")
            self.assertTrue(handoff.exists())
            self.assertTrue(unit_backup.exists())
            latest_transaction = max(
                (install_root / "var" / "transactions").glob("*.json"),
                key=lambda path: path.stat().st_mtime_ns,
            )
            self.assertEqual(
                json.loads(latest_transaction.read_text(encoding="utf-8"))["status"],
                "ready_to_commit",
            )

            stop_failure_marker.unlink()
            retry_environment = dict(systemd_environment)
            retry_environment["FAKE_RUNTIME_STATUS"] = "unknown"
            failed_after_compensation_retry = subprocess.run(
                admin_arguments,
                check=False,
                capture_output=True,
                text=True,
                env=retry_environment,
            )

            self.assertNotEqual(failed_after_compensation_retry.returncode, 0)
            self.assertEqual(systemd_state.read_text(encoding="utf-8"), "active\n")
            self.assertEqual(service_file.read_text(encoding="utf-8"), stable_unit)
            self.assertEqual(
                (release / "version.txt").read_text(encoding="utf-8"),
                "generation-systemd",
            )
            self.assertFalse(handoff.exists())
            self.assertFalse(unit_backup.exists())

            systemd_state.write_text("active\n", encoding="utf-8")
            (adapter / "version.txt").write_text(
                "generation-systemd-interrupted", encoding="utf-8"
            )
            interrupted_systemd_environment = dict(systemd_environment)
            interrupted_systemd_environment["SYSTEMD_START_INTERRUPT"] = "1"
            interrupted_systemd_upgrade = subprocess.run(
                admin_arguments,
                check=False,
                capture_output=True,
                text=True,
                env=interrupted_systemd_environment,
            )

            self.assertNotEqual(interrupted_systemd_upgrade.returncode, 0)
            self.assertEqual(systemd_state.read_text(encoding="utf-8"), "inactive\n")
            self.assertTrue(
                (install_root / "var" / "run" / "systemd-release-handoff.json").exists()
            )
            latest_transaction = max(
                (install_root / "var" / "transactions").glob("*.json"),
                key=lambda path: path.stat().st_mtime_ns,
            )
            self.assertEqual(
                json.loads(latest_transaction.read_text(encoding="utf-8"))["status"],
                "ready_to_commit",
            )

            recovery_environment = dict(systemd_environment)
            recovery_environment["FAKE_RUNTIME_STATUS"] = "unknown"
            failed_after_recovery = subprocess.run(
                admin_arguments,
                check=False,
                capture_output=True,
                text=True,
                env=recovery_environment,
            )

            self.assertNotEqual(failed_after_recovery.returncode, 0)
            self.assertEqual(
                systemd_state.read_text(encoding="utf-8"),
                "active\n",
                failed_after_recovery.stderr or failed_after_recovery.stdout,
            )
            self.assertEqual(service_file.read_text(encoding="utf-8"), stable_unit)
            self.assertEqual(
                (release / "version.txt").read_text(encoding="utf-8"),
                "generation-systemd",
            )
            self.assertEqual(
                json.loads(latest_transaction.read_text(encoding="utf-8"))["status"],
                "rolled_back",
            )

    def test_candidate_preflight_uses_the_verified_runtime_state_copy(self) -> None:
        script = ROOT / "phase1-delivery-kit/installer/preflight_candidate.sh"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            candidate = root / "candidate"
            (candidate / "adapter_service").mkdir(parents=True)
            private_runtime = candidate / "python-runtime"
            private_runtime.mkdir()
            snapshot_state = root / "snapshot-state"
            snapshot_state.mkdir()
            (snapshot_state / "adapter.json").write_text(
                '{"providerName":"verified-copy"}\n', encoding="utf-8"
            )
            preflight_root = root / "preflight"
            bin_dir = root / "bin"
            bin_dir.mkdir()
            started = root / "started"
            python_stub = bin_dir / "python"
            python_stub.write_text(
                """#!/usr/bin/env bash
if [[ " $* " == *" -c "* ]]; then
  test -f "$AI_WPS_STATE_DIR/adapter.json" || exit 7
  grep -q verified-copy "$AI_WPS_STATE_DIR/adapter.json" || exit 8
fi
if [[ " $* " == *" -m uvicorn "* ]]; then
  printf '%s\n' started > "$PREFLIGHT_STARTED"
  sleep 10
fi
exit 0
""",
                encoding="utf-8",
            )
            python_stub.chmod(0o755)
            curl_stub = bin_dir / "curl"
            curl_stub.write_text(
                """#!/usr/bin/env bash
if [ ! -f "$PREFLIGHT_STARTED" ]; then exit 1; fi
url="${@: -1}"
case "$url" in
  */health/live) printf '%s' '{"status":"live"}' ;;
  */health/ready) printf '%s' '{"status":"ready"}' ;;
  */health) printf '%s' '{"status":"ready","version":"0.23.1-alpha"}' ;;
esac
""",
                encoding="utf-8",
            )
            curl_stub.chmod(0o755)
            environment = dict(os.environ)
            environment.update(
                {
                    "AI_WPS_PREFLIGHT_STATE_SOURCE": str(snapshot_state),
                    "PATH": "{0}:{1}".format(
                        bin_dir, environment.get("PATH", "")
                    ),
                    "PREFLIGHT_STARTED": str(started),
                }
            )

            result = subprocess.run(
                [
                    "bash",
                    str(script),
                    str(python_stub),
                    str(candidate),
                    str(private_runtime),
                    "28124",
                    "0.23.1-alpha",
                    str(preflight_root),
                ],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )

            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            self.assertEqual(
                (preflight_root / "state" / "adapter.json").read_text(
                    encoding="utf-8"
                ),
                '{"providerName":"verified-copy"}\n',
            )


if __name__ == "__main__":
    unittest.main()
