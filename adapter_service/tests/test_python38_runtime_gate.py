import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PYTHON38_BIN = os.environ.get("AI_WPS_PYTHON38_BIN", "")
COMPATIBILITY_SCANNER = ROOT / "packaging/check_python38_compatibility.py"


class Python38CompatibilityScanTests(unittest.TestCase):
    def test_scan_reproduces_runtime_evaluated_builtin_generic_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_root = Path(temp_dir) / "adapter_service"
            source_root.mkdir()
            (source_root / "broken.py").write_text(
                "def load() -> tuple[dict, list]:\n    return {}, []\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(COMPATIBILITY_SCANNER), str(source_root)],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("PY38_BUILTIN_GENERIC", result.stdout)
        self.assertIn("broken.py:1", result.stdout)

    def test_scan_accepts_current_production_sources(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(COMPATIBILITY_SCANNER),
                str(ROOT / "adapter_service"),
                str(ROOT / "packaging/check_python38_compatibility.py"),
                str(ROOT / "packaging/python38_delivery_runtime_gate.py"),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("python38_compatibility_scan=passed", result.stdout)

    def test_delivery_build_clears_stale_outputs_on_any_gate_failure(self) -> None:
        failure_environments = (
            {"PYTHON_BIN": "/usr/bin/false", "PYTHON38_BIN": "/usr/bin/false"},
            {"PYTHON_BIN": sys.executable, "PYTHON38_BIN": "/usr/bin/false"},
        )
        for failure_environment in failure_environments:
            with self.subTest(failure_environment=failure_environment):
                with tempfile.TemporaryDirectory() as temp_dir:
                    archive = (
                        Path(temp_dir)
                        / "ai-wps-phase1-delivery-20260811-v0231.tar.gz"
                    )
                    checksum = archive.with_name(archive.name + ".sha256")
                    archive.write_text("stale archive", encoding="utf-8")
                    checksum.write_text("stale checksum", encoding="utf-8")
                    environment = dict(os.environ)
                    environment.update({"DATE_TAG": "20260811"})
                    environment.update(failure_environment)

                    result = subprocess.run(
                        [
                            "bash",
                            str(ROOT / "packaging/build_phase1_delivery_kit.sh"),
                            temp_dir,
                        ],
                        cwd=ROOT,
                        env=environment,
                        check=False,
                        capture_output=True,
                        text=True,
                    )

                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse(archive.exists())
                    self.assertFalse(checksum.exists())


@unittest.skipUnless(PYTHON38_BIN, "AI_WPS_PYTHON38_BIN is required for the Python 3.8 gate")
class Python38RuntimeGateTests(unittest.TestCase):
    def test_python38_reproduces_original_runtime_annotation_failure(self) -> None:
        original_signature = (
            "class WorkflowProfileCompatibilityStore:\n"
            "    def _platform_configurations(self, task_type: str) "
            "-> tuple[dict, list]:\n"
            "        return {}, []\n"
        )
        result = subprocess.run(
            [PYTHON38_BIN, "-c", original_signature],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("TypeError", result.stderr)
        self.assertIn("not subscriptable", result.stderr)

    def test_python38_imports_complete_fastapi_application(self) -> None:
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(ROOT / "adapter_service")

        result = subprocess.run(
            [
                PYTHON38_BIN,
                "-c",
                "from app.main import app; print(app.version)",
            ],
            cwd=ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "0.23.1-alpha")

    def test_final_delivery_starts_uvicorn_and_checks_key_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            environment = dict(os.environ)
            environment.update(
                {
                    "DATE_TAG": "20260811",
                    "PYTHON_BIN": sys.executable,
                    "PYTHON38_BIN": PYTHON38_BIN,
                }
            )
            build = subprocess.run(
                [
                    "bash",
                    str(ROOT / "packaging/build_phase1_delivery_kit.sh"),
                    temp_dir,
                ],
                cwd=ROOT,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(build.returncode, 0, build.stderr + build.stdout)

            archive = Path(temp_dir) / "ai-wps-phase1-delivery-20260811-v0231.tar.gz"
            archive_exists = archive.is_file()

        self.assertTrue(archive_exists)
        self.assertIn("original_failure_reproduction=passed", build.stdout)
        self.assertIn("adapter_import=passed", build.stdout)
        self.assertIn("uvicorn_start=passed", build.stdout)
        self.assertIn("key_contracts=passed", build.stdout)
        self.assertIn("python38_delivery_runtime_gate=passed", build.stdout)


if __name__ == "__main__":
    unittest.main()
