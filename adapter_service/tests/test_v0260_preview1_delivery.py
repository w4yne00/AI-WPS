import hashlib
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ASSEMBLER = ROOT / "packaging/assemble_phase1_delivery.py"
POLICY = ROOT / "packaging/delivery-sources-v0260-preview1.json"
PREPARE = ROOT / "packaging/prepare_v0260_preview1_delivery.py"
BASELINE = ROOT / (
    "dist-phase1-delivery-kit/"
    "ai-wps-phase1-delivery-20260826-d1a346b-v0253.tar.gz"
)


def _prepare_delivery(tmp_path):
    delivery = tmp_path / "delivery"
    assembled = subprocess.run(
        [
            sys.executable,
            str(ASSEMBLER),
            "--repo-root",
            str(ROOT),
            "--source-allowlist",
            str(POLICY),
            "--output",
            str(delivery),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert assembled.returncode == 0, assembled.stdout + assembled.stderr

    prepared = subprocess.run(
        [
            sys.executable,
            str(PREPARE),
            str(delivery),
            "--date",
            "20260830",
            "--baseline-archive",
            str(BASELINE),
            "--baseline-version",
            "0.25.3-alpha",
            "--acceptance-issue",
            "119",
            "--source-commit",
            "e94c561",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert prepared.returncode == 0, prepared.stdout + prepared.stderr

    template_dir = delivery / "docs/import-templates"
    template_dir.mkdir(parents=True)
    templates = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from pathlib import Path; "
                "import sys; "
                "sys.path.insert(0, sys.argv[1]); "
                "from app.services.writing_policy.imports import "
                "generate_csv_template, generate_xlsx_template; "
                "output = Path(sys.argv[2]); "
                "(output / 'writing-policies-import-template.csv').write_bytes("
                "generate_csv_template()); "
                "(output / 'writing-policies-import-template.xlsx').write_bytes("
                "generate_xlsx_template())"
            ),
            str(ROOT / "adapter_service"),
            str(template_dir),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert templates.returncode == 0, templates.stdout + templates.stderr

    for package_name in (
        "kylin-v10-arm-py38",
        "kylin-v10-arm-py38-pip-bootstrap",
    ):
        runtime_root = delivery / "packages" / package_name
        sums = runtime_root / "SHA256SUMS"
        retained = []
        for line in sums.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            _digest, relative = line.split(None, 1)
            relative = relative.lstrip("*")
            if (runtime_root / relative).is_file():
                retained.append(line)
        sums.write_text("\n".join(retained) + "\n", encoding="utf-8")
    return delivery


def test_prepare_creates_neutral_preview_identity_from_phase1_delivery_tree(tmp_path):
    delivery = _prepare_delivery(tmp_path)

    manifest = json.loads(
        (delivery / "release-manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["version"] == "0.26.0-preview.1"
    assert manifest["productChannel"] == "preview"
    assert manifest["versionRule"] == (
        "AI-WPS-WORD-EXCEL-PPT-0.26.0-preview.1-20260830-e94c561"
    )
    assert manifest["installationPolicy"] == {
        "installer": "installer/install_ai_wps.sh",
        "defaultInstallRoot": "$TARGET_HOME/ai-wps",
        "legacyInstallRoot": "$TARGET_HOME/ai-wps-phase1",
        "legacyHandling": "read-only-detect-manual-reinstall-reconfigure",
        "migratesLegacyRuntimeData": False,
        "deletesLegacyInstall": False,
    }
    assert manifest["deliveryPolicy"]["candidateAuditScript"] == (
        "scripts/audit_v0260_preview1_delivery.py"
    )
    assert manifest["deliveryPolicy"]["status"] == "candidate"
    assert "phase1" not in manifest["versionRule"].lower()

    assert (delivery / "installer/install_ai_wps.sh").is_file()
    assert not (delivery / "installer/install_phase1.sh").exists()
    assert (delivery / "scripts/ai_wps_smoke_test.sh").is_file()
    assert not (delivery / "scripts/phase1_smoke_test.sh").exists()

    lifecycle = (delivery / "scripts/python38_delivery_lifecycle_gate.py").read_text(
        encoding="utf-8"
    )
    assert "installer/install_ai_wps.sh" in lifecycle
    assert "install_phase1.sh" not in lifecycle
    assert "ai_wps_install_done=true" in lifecycle
    assert "phase1_install_done=true" not in lifecycle
    assert "audit_phase1_delivery.py" not in lifecycle
    assert 'BASELINE_VERSION = "0.25.3-alpha"' in lifecycle

    installer = (delivery / "installer/install_ai_wps.sh").read_text(encoding="utf-8")
    assert "legacy_runtime_state_exists" not in installer
    for relative in (
        "docs/operations/runtime-state-recovery.md",
        "packages/kylin-v10-arm-py38/README.md",
        "packages/adapter-start-kit/docs/autostart-guide.md",
        "packages/adapter-start-kit/docs/uvicorn-start-guide.md",
        "packages/wps-ai-assistant_1.0.0/manifest.json",
        "packages/wps-ai-assistant_1.0.0/manifest.xml",
        "packages/adapter-start-kit/adapter_service/app/__init__.py",
    ):
        content = (delivery / relative).read_text(encoding="utf-8")
        assert "install_phase1.sh" not in content
        assert "phase1_install_done=true" not in content
        assert "$HOME/ai-wps-phase1" not in content
    assert "Phase 1" not in (
        delivery / "packages/wps-ai-assistant_1.0.0/manifest.json"
    ).read_text(encoding="utf-8")


def test_preview_installer_only_reports_legacy_phase1_and_preserves_its_data(tmp_path):
    delivery = _prepare_delivery(tmp_path)
    target_home = tmp_path / "target-home"
    legacy = target_home / "ai-wps-phase1"
    (legacy / "config").mkdir(parents=True)
    (legacy / "run").mkdir()
    (legacy / "config/adapter.json").write_text(
        '{"providerApiKey": "do-not-read"}\n', encoding="utf-8"
    )
    (legacy / "run/provider_api_key").write_text("legacy-secret\n", encoding="utf-8")
    (legacy / "run/writing_policies.db").write_bytes(b"legacy-db")
    before = {
        path.relative_to(legacy): path.read_bytes()
        for path in legacy.rglob("*")
        if path.is_file()
    }
    jsaddons = target_home / "jsaddons"
    result = subprocess.run(
        ["bash", str(delivery / "installer/install_ai_wps.sh")],
        cwd=delivery,
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "HOME": str(target_home),
            "AI_WPS_INSTALL_ROOT": str(target_home / "ai-wps"),
            "AI_WPS_LEGACY_INSTALL_ROOT": str(legacy),
            "WPS_JSADDONS_DIR": str(jsaddons),
            "PYTHON_BIN": "/usr/bin/false",
        },
    )

    assert "legacy_phase1_install_detected=true" in result.stdout
    assert "legacy_phase1_action=read_only" in result.stdout
    assert "manual_reinstall_required=true" in result.stdout
    assert "manual_reconfigure_required=true" in result.stdout
    assert "legacy_runtime_data_migrated=false" in result.stdout
    assert "legacy_install_deleted=false" in result.stdout
    assert {
        path.relative_to(legacy): path.read_bytes()
        for path in legacy.rglob("*")
        if path.is_file()
    } == before


def test_preview_installer_rejects_runtime_path_overlapping_legacy_install(tmp_path):
    delivery = _prepare_delivery(tmp_path)
    target_home = tmp_path / "target-home"
    legacy = target_home / "ai-wps-phase1"
    legacy_state = legacy / "state"
    legacy_state.mkdir(parents=True)
    sentinel = legacy_state / "adapter.json"
    sentinel.write_text('{"legacy":true}\n', encoding="utf-8")
    before = sentinel.read_bytes()
    result = subprocess.run(
        ["bash", str(delivery / "installer/install_ai_wps.sh")],
        cwd=delivery,
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "HOME": str(target_home),
            "AI_WPS_INSTALL_ROOT": str(target_home / "ai-wps"),
            "AI_WPS_STATE_DIR": str(legacy_state),
            "WPS_JSADDONS_DIR": str(target_home / "jsaddons"),
            "PYTHON_BIN": "/usr/bin/false",
        },
    )

    assert result.returncode != 0
    assert "preview_path_conflicts_with_legacy name=state_dir" in result.stdout
    assert sentinel.read_bytes() == before


def test_preview_installer_rejects_legacy_install_root_override(tmp_path):
    delivery = _prepare_delivery(tmp_path)
    target_home = tmp_path / "target-home"
    legacy = target_home / "ai-wps-phase1"
    legacy.mkdir(parents=True)
    result = subprocess.run(
        ["bash", str(delivery / "installer/install_ai_wps.sh")],
        cwd=delivery,
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "HOME": str(target_home),
            "AI_WPS_INSTALL_ROOT": str(legacy),
            "AI_WPS_LEGACY_INSTALL_ROOT": str(tmp_path / "decoy-legacy"),
            "WPS_JSADDONS_DIR": str(target_home / "jsaddons"),
            "PYTHON_BIN": "/usr/bin/false",
        },
    )

    assert result.returncode != 0
    assert "preview_path_conflicts_with_legacy name=install_root" in result.stdout


def test_preview_installer_rejects_existing_non_preview_install_root(tmp_path):
    delivery = _prepare_delivery(tmp_path)
    target_home = tmp_path / "target-home"
    existing_root = target_home / "previous-install"
    existing_state = existing_root / "state"
    existing_state.mkdir(parents=True)
    sentinel = existing_state / "adapter.json"
    sentinel.write_text('{"legacy":true}\n', encoding="utf-8")
    before = sentinel.read_bytes()
    result = subprocess.run(
        ["bash", str(delivery / "installer/install_ai_wps.sh")],
        cwd=delivery,
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "HOME": str(target_home),
            "AI_WPS_INSTALL_ROOT": str(existing_root),
            "WPS_JSADDONS_DIR": str(target_home / "jsaddons"),
            "PYTHON_BIN": sys.executable,
        },
    )

    assert result.returncode != 0
    assert "preview_existing_install_manifest_required" in result.stdout
    assert sentinel.read_bytes() == before


def test_preview_audit_accepts_neutral_tree_and_rejects_phase1_release_identity(tmp_path):
    delivery = _prepare_delivery(tmp_path)
    audit = delivery / "scripts/audit_v0260_preview1_delivery.py"
    generated = subprocess.run(
        [
            sys.executable,
            str(ROOT / "packaging/audit_phase1_delivery.py"),
            str(delivery),
            "--write-hashes",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert generated.returncode == 0, generated.stdout + generated.stderr
    accepted = subprocess.run(
        [sys.executable, str(audit), str(delivery)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr
    assert "status=candidate" in accepted.stdout

    manifest_path = delivery / "release-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["versionRule"] = (
        "AI-WPS-P1-WORD-EXCEL-PPT-0.26.0-preview.1-20260830-e94c561"
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    rejected = subprocess.run(
        [sys.executable, str(audit), str(delivery)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert rejected.returncode != 0
    assert "V0260_VERSION_RULE_INVALID" in rejected.stdout


def test_preview_audit_rejects_phase1_lifecycle_identity(tmp_path):
    delivery = _prepare_delivery(tmp_path)
    audit = delivery / "scripts/audit_v0260_preview1_delivery.py"
    generated = subprocess.run(
        [
            sys.executable,
            str(ROOT / "packaging/audit_phase1_delivery.py"),
            str(delivery),
            "--write-hashes",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert generated.returncode == 0, generated.stdout + generated.stderr
    lifecycle_path = delivery / "scripts/python38_delivery_lifecycle_gate.py"
    lifecycle_path.write_text(
        lifecycle_path.read_text(encoding="utf-8")
        + "\n# install_phase1.sh must not be the Preview lifecycle entrypoint\n",
        encoding="utf-8",
    )

    rejected = subprocess.run(
        [sys.executable, str(audit), str(delivery)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert rejected.returncode != 0
    assert "V0260_LIFECYCLE_IDENTITY_INVALID" in rejected.stdout


def test_preview_tree_passes_generic_audit_and_writes_verifiable_hash_manifest(tmp_path):
    delivery = _prepare_delivery(tmp_path)
    generic_audit = ROOT / "packaging/audit_phase1_delivery.py"
    candidate_audit = delivery / "scripts/audit_v0260_preview1_delivery.py"

    generated = subprocess.run(
        [sys.executable, str(generic_audit), str(delivery), "--write-hashes"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert generated.returncode == 0, generated.stdout + generated.stderr
    assert "delivery_audit=passed status=candidate" in generated.stdout

    hashes = json.loads(
        (delivery / "release-file-hashes.json").read_text(encoding="utf-8")
    )
    assert hashes["version"] == "0.26.0-preview.1"
    assert hashes["algorithm"] == "sha256"
    assert hashes["files"]

    verified = subprocess.run(
        [sys.executable, str(candidate_audit), str(delivery)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert verified.returncode == 0, verified.stdout + verified.stderr

    manifest = json.loads(
        (delivery / "release-manifest.json").read_text(encoding="utf-8")
    )
    archive_name = manifest["candidateEvidence"]["archiveName"]
    archive = tmp_path / archive_name
    with tarfile.open(archive, "w:gz") as handle:
        handle.add(delivery, arcname=delivery.name)
    checksum_file = tmp_path / (archive_name + ".sha256")
    checksum_file.write_text(
        "{0}  {1}\n".format(
            hashlib.sha256(archive.read_bytes()).hexdigest(), archive_name
        ),
        encoding="utf-8",
    )
    checked_archive = subprocess.run(
        [
            sys.executable,
            str(candidate_audit),
            str(delivery),
            "--archive",
            str(archive),
            "--checksum-file",
            str(checksum_file),
            "--expected-archive-name",
            archive_name,
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert checked_archive.returncode == 0, (
        checked_archive.stdout + checked_archive.stderr
    )


def test_preview_audit_rejects_missing_hash_manifest(tmp_path):
    delivery = _prepare_delivery(tmp_path)
    generic_audit = ROOT / "packaging/audit_phase1_delivery.py"
    candidate_audit = delivery / "scripts/audit_v0260_preview1_delivery.py"
    generated = subprocess.run(
        [sys.executable, str(generic_audit), str(delivery), "--write-hashes"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert generated.returncode == 0, generated.stdout + generated.stderr
    (delivery / "release-file-hashes.json").unlink()

    rejected = subprocess.run(
        [sys.executable, str(candidate_audit), str(delivery)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert rejected.returncode != 0
    assert "V0260_REQUIRED_OUTPUT_MISSING release-file-hashes.json" in rejected.stdout


def test_preview_build_and_prepare_scripts_are_provenance_inputs():
    provenance = (ROOT / "packaging/check_delivery_source_provenance.py").read_text(
        encoding="utf-8"
    )
    assert '"packaging/build_v0260_preview1_delivery_kit.sh"' in provenance
    assert '"packaging/prepare_v0260_preview1_delivery.py"' in provenance


def test_preview_build_requires_v0253_baseline_before_creating_output(tmp_path):
    build = ROOT / "packaging/build_v0260_preview1_delivery_kit.sh"
    output = tmp_path / "dist"
    missing_baseline = tmp_path / "missing-v0253.tar.gz"
    result = subprocess.run(
        ["bash", str(build), str(output)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "DATE_TAG": "20260830",
            "AI_WPS_V0253_BASELINE_ARCHIVE": str(missing_baseline),
        },
    )

    assert result.returncode != 0
    assert "v0253_baseline_archive_required=true" in result.stdout
    assert not output.exists()
