import hashlib
import importlib.util
import json
import os
import socket
import subprocess
import sys
import tarfile
import time
from pathlib import Path
import pytest


ROOT = Path(__file__).resolve().parents[2]
ASSEMBLER = ROOT / "packaging/assemble_phase1_delivery.py"
POLICY = ROOT / "packaging/delivery-sources-v0260-preview1.json"
PREPARE = ROOT / "packaging/prepare_v0260_preview1_delivery.py"
BASELINE = ROOT / (
    "dist-phase1-delivery-kit/"
    "ai-wps-phase1-delivery-20260826-d1a346b-v0253.tar.gz"
)
EXPECTED_TASKS = frozenset(
    {
        "word.smart_write",
        "word.smart_imitation",
        "word.document_review",
        "word.format_review",
        "excel.analysis",
        "excel.formula_assistant",
        "excel.smart_fill",
        "ppt.slide_assistant",
        "ppt.structure_review",
    }
)


def _installer_environment(target_home, **updates):
    target_tools = target_home.parent / "target-tools"
    target_tools.mkdir(exist_ok=True)
    getent = target_tools / "getent"
    getent.write_text(
        "#!/usr/bin/env bash\n"
        'if [ "${1:-}" = "passwd" ]; then\n'
        '  printf \'%s:x:%s:%s::%s:/bin/sh\\n\' "$2" "$(id -u)" "$(id -g)" "$HOME"\n'
        "  exit 0\n"
        "fi\n"
        "exit 2\n",
        encoding="utf-8",
    )
    getent.chmod(0o755)
    ps = target_tools / "ps"
    ps.write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$#" -eq 4 ] && [ "$1" = "-u" ] && [ "$3" = "-o" ] '
        '&& [ "$4" = "comm=" ]; then\n'
        "  exit 0\n"
        "fi\n"
        "exit 2\n",
        encoding="utf-8",
    )
    ps.chmod(0o755)
    environment = {
        **os.environ,
        "HOME": str(target_home),
        "PATH": str(target_tools) + os.pathsep + os.environ.get("PATH", ""),
    }
    environment.update(updates)
    return environment


def _prepare_delivery(tmp_path, source_commit="e94c561"):
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
            "120",
            "--source-commit",
            source_commit,
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
        env=_installer_environment(
            target_home,
            AI_WPS_INSTALL_ROOT=str(target_home / "ai-wps"),
            AI_WPS_LEGACY_INSTALL_ROOT=str(legacy),
            WPS_JSADDONS_DIR=str(jsaddons),
            PYTHON_BIN="/usr/bin/false",
        ),
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


def _free_tcp_port():
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


def _port_is_listening(port):
    check = subprocess.run(
        ["lsof", "-ti", "TCP:{0}".format(port), "-sTCP:LISTEN"],
        check=False,
        capture_output=True,
        text=True,
    )
    return bool(check.stdout.strip())


def test_preview_installer_releases_occupied_port_without_touching_legacy_data(tmp_path):
    delivery = _prepare_delivery(tmp_path)
    target_home = tmp_path / "occupied-port-home"
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
    port = _free_tcp_port()
    listener = subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "import socket, sys, time\n"
                "server = socket.socket()\n"
                "server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
                "server.bind(('127.0.0.1', int(sys.argv[1])))\n"
                "server.listen(1)\n"
                "time.sleep(120)\n"
            ),
            str(port),
        ]
    )
    try:
        for _ in range(50):
            if _port_is_listening(port):
                break
            time.sleep(0.05)
        else:
            raise AssertionError("test listener did not bind port {0}".format(port))

        result = subprocess.run(
            ["bash", str(delivery / "installer/install_ai_wps.sh")],
            cwd=delivery,
            check=False,
            capture_output=True,
            text=True,
            env=_installer_environment(
                target_home,
                AI_WPS_INSTALL_ROOT=str(target_home / "ai-wps"),
                WPS_JSADDONS_DIR=str(target_home / "jsaddons"),
                AI_WPS_SYSTEMD_SERVICE_FILE=str(tmp_path / "no-systemd/ai-wps.service"),
                PORT=str(port),
                AI_WPS_CANDIDATE_PORT=str(port + 1),
                PYTHON_BIN="/usr/bin/false",
            ),
        )
    finally:
        if listener.poll() is None:
            listener.terminate()
            try:
                listener.wait(timeout=5)
            except subprocess.TimeoutExpired:
                listener.kill()
                listener.wait(timeout=5)

    assert "install_failed=adapter_port_still_listening" not in result.stdout
    assert "adapter_state_transition_lock=stopped port={0}".format(port) in result.stdout
    assert "legacy_phase1_install_detected=true" in result.stdout
    assert "legacy_runtime_data_migrated=false" in result.stdout
    assert "legacy_install_deleted=false" in result.stdout
    assert {
        path.relative_to(legacy): path.read_bytes()
        for path in legacy.rglob("*")
        if path.is_file()
    } == before
    assert listener.returncode not in (None, 0)
    assert not _port_is_listening(port)


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
        env=_installer_environment(
            target_home,
            AI_WPS_INSTALL_ROOT=str(target_home / "ai-wps"),
            AI_WPS_STATE_DIR=str(legacy_state),
            WPS_JSADDONS_DIR=str(target_home / "jsaddons"),
            PYTHON_BIN="/usr/bin/false",
        ),
    )

    assert result.returncode != 0
    assert "preview_path_conflicts_with_legacy name=state_dir" in result.stdout
    assert sentinel.read_bytes() == before


def test_preview_installer_rejects_lexically_normalized_legacy_path(tmp_path):
    delivery = _prepare_delivery(tmp_path)
    target_home = tmp_path / "target-home"
    legacy = target_home / "ai-wps-phase1"
    legacy_state = legacy / "state"
    legacy_state.mkdir(parents=True)
    sentinel = legacy_state / "adapter.json"
    sentinel.write_text('{"legacy":true}\n', encoding="utf-8")
    escaped_path = target_home / "missing" / ".." / "ai-wps-phase1" / "state"
    result = subprocess.run(
        ["bash", str(delivery / "installer/install_ai_wps.sh")],
        cwd=delivery,
        check=False,
        capture_output=True,
        text=True,
        env=_installer_environment(
            target_home,
            AI_WPS_INSTALL_ROOT=str(target_home / "ai-wps"),
            AI_WPS_STATE_DIR=str(escaped_path),
            WPS_JSADDONS_DIR=str(target_home / "jsaddons"),
            PYTHON_BIN="/usr/bin/false",
        ),
    )

    assert result.returncode != 0
    assert "preview_path_conflicts_with_legacy name=state_dir" in result.stdout
    assert sentinel.read_bytes() == b'{"legacy":true}\n'


def test_preview_installer_rejects_symlinked_managed_path_component(tmp_path):
    delivery = _prepare_delivery(tmp_path)
    target_home = tmp_path / "target-home"
    outside = tmp_path / "outside"
    linked = target_home / "linked"
    target_home.mkdir()
    outside.mkdir()
    linked.symlink_to(outside, target_is_directory=True)
    result = subprocess.run(
        ["bash", str(delivery / "installer/install_ai_wps.sh")],
        cwd=delivery,
        check=False,
        capture_output=True,
        text=True,
        env=_installer_environment(
            target_home,
            AI_WPS_INSTALL_ROOT=str(target_home / "ai-wps"),
            AI_WPS_STATE_DIR=str(linked / "state"),
            WPS_JSADDONS_DIR=str(target_home / "jsaddons"),
            PYTHON_BIN=sys.executable,
        ),
    )

    assert result.returncode != 0
    assert "preview_symlink_path_component name=state_dir" in result.stdout


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
        env=_installer_environment(
            target_home,
            AI_WPS_INSTALL_ROOT=str(legacy),
            AI_WPS_LEGACY_INSTALL_ROOT=str(tmp_path / "decoy-legacy"),
            WPS_JSADDONS_DIR=str(target_home / "jsaddons"),
            PYTHON_BIN="/usr/bin/false",
        ),
    )

    assert result.returncode != 0
    assert "preview_path_conflicts_with_legacy name=install_root" in result.stdout


def test_preview_installer_rejects_managed_path_outside_target_home(tmp_path):
    delivery = _prepare_delivery(tmp_path)
    target_home = tmp_path / "target-home"
    outside_root = tmp_path / "sibling-root"
    target_home.mkdir()
    outside_root.mkdir()
    result = subprocess.run(
        ["bash", str(delivery / "installer/install_ai_wps.sh")],
        cwd=delivery,
        check=False,
        capture_output=True,
        text=True,
        env=_installer_environment(
            target_home,
            AI_WPS_INSTALL_ROOT=str(outside_root / "ai-wps"),
            WPS_JSADDONS_DIR=str(target_home / "jsaddons"),
            PYTHON_BIN=sys.executable,
        ),
    )

    assert result.returncode != 0
    assert "preview_path_outside_target_home name=install_root" in result.stdout


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
        env=_installer_environment(
            target_home,
            AI_WPS_INSTALL_ROOT=str(existing_root),
            WPS_JSADDONS_DIR=str(target_home / "jsaddons"),
            PYTHON_BIN=sys.executable,
        ),
    )

    assert result.returncode != 0
    assert "preview_existing_install_manifest_required" in result.stdout
    assert sentinel.read_bytes() == before


def test_preview_installer_rejects_incomplete_preview_install_manifest(tmp_path):
    delivery = _prepare_delivery(tmp_path)
    target_home = tmp_path / "target-home"
    existing_root = target_home / "previous-preview"
    release = existing_root / "releases" / "0.26.0-preview.1"
    current = existing_root / "current"
    state = existing_root / "state"
    release.mkdir(parents=True)
    current.symlink_to(Path("releases") / "0.26.0-preview.1")
    state.mkdir()
    sentinel = state / "adapter.json"
    sentinel.write_text('{"preserve":true}\n', encoding="utf-8")
    (release / "release-manifest.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "product": "AI-WPS",
                "productChannel": "preview",
                "version": "0.26.0-preview.1",
            }
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        ["bash", str(delivery / "installer/install_ai_wps.sh")],
        cwd=delivery,
        check=False,
        capture_output=True,
        text=True,
        env=_installer_environment(
            target_home,
            AI_WPS_INSTALL_ROOT=str(existing_root),
            WPS_JSADDONS_DIR=str(target_home / "jsaddons"),
            PYTHON_BIN=sys.executable,
        ),
    )

    assert result.returncode != 0
    assert "preview_existing_install_manifest_invalid" in result.stdout
    assert sentinel.read_bytes() == b'{"preserve":true}\n'


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


def test_preview_audit_accepts_full_source_commit_with_short_version_rule(tmp_path):
    delivery = _prepare_delivery(
        tmp_path,
        "3e64066d5794b3348d60535f35a9ade238b3a891",
    )
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

    verified = subprocess.run(
        [sys.executable, str(candidate_audit), str(delivery)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert verified.returncode == 0, verified.stdout + verified.stderr


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
    assert '"formal-plugin-kit/tests/support/*.js"' in provenance or '"formal-plugin-kit/tests/support"' in provenance


def test_preview_provenance_validates_baseline_archive(tmp_path, monkeypatch):
    import importlib.util
    provenance_path = ROOT / "packaging/check_delivery_source_provenance.py"
    spec = importlib.util.spec_from_file_location("provenance_module", provenance_path)
    prov = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prov)

    allowlist = ROOT / "packaging/delivery-sources-v0260-preview1.json"

    def make_fake_git(untracked_file=None, dirty_file=None):
        def fake_git(repo_root, args):
            if args == ["rev-parse", "HEAD"]:
                return subprocess.CompletedProcess(args=args, returncode=0, stdout="testcommit\n", stderr="")
            if args[0] == "ls-files" and args[1] == "--":
                return subprocess.CompletedProcess(args=args, returncode=0, stdout="formal-plugin-kit/tests/layout-smoke.test.js\n", stderr="")
            if args[0] == "ls-files" and args[1] == "--error-unmatch":
                target = args[3]
                if untracked_file and target == untracked_file:
                    return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="error")
                return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
            if args[0] == "status":
                if dirty_file:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout=f" M {dirty_file}\n", stderr="")
                return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
        return fake_git

    monkeypatch.setattr(prov, "_git", make_fake_git())

    # 1. Missing baseline archive argument
    with pytest.raises(prov.ProvenanceFailure) as exc_info:
        prov.verify(ROOT, allowlist, "testcommit", baseline_archive=None)
    assert "DELIVERY_SOURCE_BASELINE_ARCHIVE_REQUIRED" in str(exc_info.value)

    # 2. Baseline archive outside repo
    outside_archive = tmp_path / "outside-v0253.tar.gz"
    outside_archive.write_bytes(b"dummy")
    with pytest.raises(prov.ProvenanceFailure) as exc_info:
        prov.verify(ROOT, allowlist, "testcommit", baseline_archive=outside_archive)
    assert "DELIVERY_SOURCE_PATH_OUTSIDE_REPOSITORY" in str(exc_info.value)

    # 3. Untracked archive failure
    monkeypatch.setattr(prov, "_git", make_fake_git(untracked_file="dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260826-d1a346b-v0253.tar.gz"))
    valid_archive = ROOT / "dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260826-d1a346b-v0253.tar.gz"
    with pytest.raises(prov.ProvenanceFailure) as exc_info:
        prov.verify(ROOT, allowlist, "testcommit", baseline_archive=valid_archive)
    assert "DELIVERY_SOURCE_NOT_TRACKED" in str(exc_info.value)

    # 4. Valid tracked baseline archive
    monkeypatch.setattr(prov, "_git", make_fake_git())
    count = prov.verify(ROOT, allowlist, "testcommit", baseline_archive=valid_archive)
    assert count > 0


def test_preview_lifecycle_uses_isolated_home_lookup_without_relaxing_identity(tmp_path):
    lifecycle_path = ROOT / "packaging/python38_preview1_delivery_lifecycle_gate.py"
    spec = importlib.util.spec_from_file_location("preview_lifecycle", lifecycle_path)
    assert spec is not None and spec.loader is not None
    lifecycle = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lifecycle)

    environment = lifecycle.install_environment(tmp_path / "lifecycle", 18101)
    lookup = Path(environment["PATH"].split(os.pathsep, 1)[0]) / "getent"
    resolved = subprocess.run(
        [str(lookup), "passwd", environment["AI_WPS_TARGET_USER"]],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert resolved.returncode == 0
    assert resolved.stdout.strip().split(":")[5] == environment["HOME"]
    assert '"--target-user"' in lifecycle_path.read_text(encoding="utf-8")
    assert '"--target-home"' not in lifecycle_path.read_text(encoding="utf-8")


def test_preview_upgrade_allows_runtime_migration_fields_while_preserving_user_config(
    tmp_path, monkeypatch
):
    lifecycle_path = ROOT / "packaging/python38_preview1_delivery_lifecycle_gate.py"
    spec = importlib.util.spec_from_file_location("preview_lifecycle_upgrade", lifecycle_path)
    assert spec is not None and spec.loader is not None
    lifecycle = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lifecycle)

    calls = []

    def fake_run_installer(delivery_root, environment, expected_returncode=0, updates=None):
        del delivery_root, expected_returncode, updates
        state_root = Path(environment["AI_WPS_INSTALL_ROOT"]) / "state"
        state_root.mkdir(parents=True, exist_ok=True)
        calls.append(len(calls) + 1)
        if len(calls) == 2:
            payload = json.loads((state_root / "adapter.json").read_text(encoding="utf-8"))
            payload["migrationState"] = {"workflowProfilesVersion": 1}
            (state_root / "adapter.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        return subprocess.CompletedProcess(
            args=["fake-installer"],
            returncode=0,
            stdout="ai_wps_install_done=true\n",
            stderr="",
        )

    monkeypatch.setattr(lifecycle, "run_installer", fake_run_installer)
    monkeypatch.setattr(lifecycle, "stop_adapter", lambda environment: None)
    monkeypatch.setattr(lifecycle, "verify_install", lambda environment: None)

    lifecycle.run_preview_upgrade(tmp_path / "delivery", tmp_path, lambda: 18101)
    assert calls == [1, 2]


def test_preview_build_requires_v0253_baseline_before_creating_output(tmp_path):
    build = ROOT / "packaging/build_v0260_preview1_delivery_kit.sh"
    output = tmp_path / "dist"
    missing_baseline = tmp_path / "missing-v0253.tar.gz"
    git_sentinel = tmp_path / "git-called"
    tools = tmp_path / "tools"
    tools.mkdir()
    fake_git = tools / "git"
    fake_git.write_text(
        "#!/usr/bin/env bash\n"
        ': > "${AI_WPS_GIT_SENTINEL:?}"\n'
        "exit 97\n",
        encoding="utf-8",
    )
    fake_git.chmod(0o755)
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
            "AI_WPS_GIT_SENTINEL": str(git_sentinel),
            "PATH": str(tools) + os.pathsep + os.environ.get("PATH", ""),
        },
    )

    assert result.returncode != 0
    assert "v0253_baseline_archive_required=true" in result.stdout
    assert not git_sentinel.exists()
    assert not output.exists()


def test_preview_build_uses_preview_lifecycle_gate():
    build = (ROOT / "packaging/build_v0260_preview1_delivery_kit.sh").read_text(
        encoding="utf-8"
    )

    assert "packaging/python38_preview1_delivery_lifecycle_gate.py" in build
    assert "packaging/python38_delivery_lifecycle_gate.py" not in build


def test_preview_delivery_tree_contains_all_nine_tasks_and_smart_fill_assets(tmp_path):
    delivery = _prepare_delivery(tmp_path)

    manifest = json.loads((delivery / "release-manifest.json").read_text(encoding="utf-8"))
    assert manifest["adapter"]["systemPromptCount"] == 9
    assert manifest["excelSmartFillAssets"] == {
        "operationsGuide": "docs/operations/model-excel-smart-fill-contract.md",
        "workflowGuide": "docs/operations/workflow-platform-excel-smart-fill.md",
        "referenceWorkflow": "reference-workflows/excel-smart-fill-v1.yml",
        "systemPrompt": "packages/adapter-start-kit/adapter_service/system_prompts/excel-smart-fill.md",
    }

    prompt_manifest_path = delivery / manifest["adapter"]["systemPromptManifest"]
    prompt_manifest = json.loads(prompt_manifest_path.read_text(encoding="utf-8"))
    assert prompt_manifest["release"] == "0.26.0-preview.1"
    assert len(prompt_manifest["tasks"]) == 9
    assert set(prompt_manifest["tasks"].keys()) == EXPECTED_TASKS

    smart_fill_prompt = prompt_manifest_path.parent / prompt_manifest["tasks"]["excel.smart_fill"]["file"]
    assert smart_fill_prompt.is_file()
    assert hashlib.sha256(smart_fill_prompt.read_bytes()).hexdigest() == prompt_manifest["tasks"]["excel.smart_fill"]["sha256"]
    assert "excel.smart_fill.v2" in smart_fill_prompt.read_text(encoding="utf-8")

    assert (delivery / "docs/operations/model-excel-smart-fill-contract.md").is_file()
    assert (delivery / "docs/operations/workflow-platform-excel-smart-fill.md").is_file()
    ref_wf = delivery / "reference-workflows/excel-smart-fill-v1.yml"
    assert ref_wf.is_file()
    assert "excel.smart_fill.v2" in ref_wf.read_text(encoding="utf-8")

    icon_path = delivery / "packages/wps-ai-assistant-et_1.0.0/assets/icon-excel-smart-fill.png"
    assert icon_path.is_file()
    assert icon_path.stat().st_size > 0

    assert (delivery / "packages/adapter-start-kit/adapter_service/app/services/excel/smart_fill.py").is_file()
    assert (delivery / "packages/adapter-start-kit/adapter_service/app/services/excel/smart_fill_jobs.py").is_file()


def test_preview_audit_rejects_missing_or_substituted_prompt_task(tmp_path):
    delivery = _prepare_delivery(tmp_path)
    audit = delivery / "scripts/audit_v0260_preview1_delivery.py"
    release_manifest_path = delivery / "release-manifest.json"
    original_release_manifest_text = release_manifest_path.read_text(encoding="utf-8")
    manifest = json.loads(original_release_manifest_text)
    prompt_manifest_path = delivery / manifest["adapter"]["systemPromptManifest"]
    original_manifest_text = prompt_manifest_path.read_text(encoding="utf-8")

    # Tamper 1: Replace word.smart_write with unrelated.task (maintaining count=9, rewrite hashes)
    tampered_data = json.loads(original_manifest_text)
    item = tampered_data["tasks"].pop("word.smart_write")
    tampered_data["tasks"]["word.unrelated_task"] = item
    prompt_manifest_path.write_text(json.dumps(tampered_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    subprocess.run(
        [sys.executable, str(ROOT / "packaging/audit_phase1_delivery.py"), str(delivery), "--write-hashes"],
        cwd=ROOT,
        check=True,
    )
    rejected = subprocess.run(
        [sys.executable, str(audit), str(delivery)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert rejected.returncode != 0
    assert "V0260_PROMPT_TASKS_MISMATCH" in rejected.stdout

    # Tamper 2: Delete word.smart_write in prompt manifest only (count becomes 8)
    tampered_data = json.loads(original_manifest_text)
    del tampered_data["tasks"]["word.smart_write"]
    prompt_manifest_path.write_text(json.dumps(tampered_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    rejected = subprocess.run(
        [sys.executable, str(audit), str(delivery)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert rejected.returncode != 0
    assert "V0260_PROMPT_TASK_COUNT_INVALID" in rejected.stdout

    # Tamper 3: Delete word.smart_write and adjust release manifest count to 8 (so phase1 passes, but preview audit fails)
    tampered_manifest = json.loads(original_release_manifest_text)
    tampered_manifest["adapter"]["systemPromptCount"] = 8
    release_manifest_path.write_text(json.dumps(tampered_manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    subprocess.run(
        [sys.executable, str(ROOT / "packaging/audit_phase1_delivery.py"), str(delivery), "--write-hashes"],
        cwd=ROOT,
        check=True,
    )
    rejected = subprocess.run(
        [sys.executable, str(audit), str(delivery)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert rejected.returncode != 0
    assert "V0260_ADAPTER_IDENTITY_INVALID" in rejected.stdout

    prompt_manifest_path.write_text(original_manifest_text, encoding="utf-8")
    release_manifest_path.write_text(original_release_manifest_text, encoding="utf-8")


def test_preview_audit_rejects_corrupted_plugin_js_syntax(tmp_path):
    delivery = _prepare_delivery(tmp_path)
    audit = delivery / "scripts/audit_v0260_preview1_delivery.py"
    target_js = delivery / "packages/wps-ai-assistant-et_1.0.0/taskpane.js"
    original_content = target_js.read_text(encoding="utf-8")

    target_js.write_text(original_content + "\nfunction ( {\n", encoding="utf-8")
    subprocess.run(
        [sys.executable, str(ROOT / "packaging/audit_phase1_delivery.py"), str(delivery), "--write-hashes"],
        cwd=ROOT,
        check=True,
    )
    rejected = subprocess.run(
        [sys.executable, str(audit), str(delivery)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert rejected.returncode != 0
    assert "V0260_PLUGIN_JS_SYNTAX_INVALID packages/wps-ai-assistant-et_1.0.0/taskpane.js" in rejected.stdout

    target_js.write_text(original_content, encoding="utf-8")


def _assembled_plugin_env(delivery: Path) -> dict:
    return {
        **os.environ,
        "AI_WPS_HASH_CONTRACT_PYTHON": sys.executable,
        "AI_WPS_WORD_PLUGIN_DIR": str(delivery / "packages/wps-ai-assistant_1.0.0"),
        "AI_WPS_ET_PLUGIN_DIR": str(delivery / "packages/wps-ai-assistant-et_1.0.0"),
        "AI_WPS_PPT_PLUGIN_DIR": str(delivery / "packages/wps-ai-assistant-wpp_1.0.0"),
        "AI_WPS_DELIVERY_ROOT": str(delivery),
    }


def test_preview_assembled_plugins_pass_node_contract_suite(tmp_path):
    delivery = _prepare_delivery(tmp_path)
    env = _assembled_plugin_env(delivery)
    result = subprocess.run(
        ["node", "--test"] + [str(p) for p in sorted((ROOT / "formal-plugin-kit/tests").glob("*.test.js"))],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_preview_assembled_plugins_fail_node_contract_when_corrupted(tmp_path):
    delivery = _prepare_delivery(tmp_path)
    target_helpers = delivery / "packages/wps-ai-assistant-et_1.0.0/taskpane-helpers.js"
    original = target_helpers.read_text(encoding="utf-8")
    target_helpers.write_text('throw new Error("delivery plugin corrupted");\n' + original, encoding="utf-8")
    env = _assembled_plugin_env(delivery)
    result = subprocess.run(
        ["node", "--test", str(ROOT / "formal-plugin-kit/tests/excel-smart-fill.test.js")],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "delivery plugin corrupted" in result.stderr or "delivery plugin corrupted" in result.stdout


def test_preview_audit_rejects_smart_fill_contract_violations(tmp_path):
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

    # Tamper with prompt
    prompt_file = delivery / "packages/adapter-start-kit/adapter_service/system_prompts/excel-smart-fill.md"
    original_prompt = prompt_file.read_text(encoding="utf-8")
    prompt_file.write_text(original_prompt.replace("excel.smart_fill.v2", "excel.smart_fill.invalid"), encoding="utf-8")

    rejected = subprocess.run(
        [sys.executable, str(audit), str(delivery)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert rejected.returncode != 0
    assert "V0260_PROMPT_HASH_INVALID excel.smart_fill" in rejected.stdout or "V0260_SMART_FILL_SCHEMA_MISSING" in rejected.stdout
    prompt_file.write_text(original_prompt, encoding="utf-8")

    # Tamper with ribbon (missing button)
    ribbon_file = delivery / "packages/wps-ai-assistant-et_1.0.0/ribbon.xml"
    original_ribbon = ribbon_file.read_text(encoding="utf-8")
    ribbon_file.write_text(original_ribbon.replace('id="btnAiExcelSmartFill"', 'id="btnOther"'), encoding="utf-8")

    rejected = subprocess.run(
        [sys.executable, str(audit), str(delivery)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert rejected.returncode != 0
    assert "V0260_SMART_FILL_RIBBON_MISSING" in rejected.stdout
    ribbon_file.write_text(original_ribbon, encoding="utf-8")

    # Tamper with taskpane js (introduce undo)
    taskpane_file = delivery / "packages/wps-ai-assistant-et_1.0.0/taskpane.js"
    original_taskpane = taskpane_file.read_text(encoding="utf-8")
    taskpane_file.write_text(original_taskpane + "\nfunction OnUndo() {}\n", encoding="utf-8")

    rejected = subprocess.run(
        [sys.executable, str(audit), str(delivery)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert rejected.returncode != 0
    assert "V0260_SMART_FILL_UNDO_PROMISE" in rejected.stdout
    taskpane_file.write_text(original_taskpane, encoding="utf-8")

    # Tamper with reference workflow (corrupt contract version)
    workflow_file = delivery / "reference-workflows/excel-smart-fill-v1.yml"
    original_workflow = workflow_file.read_text(encoding="utf-8")
    workflow_file.write_text(original_workflow.replace("excel.smart_fill.v2", "excel.smart_fill.v3"), encoding="utf-8")

    rejected = subprocess.run(
        [sys.executable, str(audit), str(delivery)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert rejected.returncode != 0
    assert "V0260_SMART_FILL_REFERENCE_WORKFLOW_INVALID" in rejected.stdout
    workflow_file.write_text(original_workflow, encoding="utf-8")


def test_preview_acceptance_template_covers_nine_tasks_and_pending_status(tmp_path):
    delivery = _prepare_delivery(tmp_path)
    acceptance = (delivery / "docs/v0260-preview1-target-machine-acceptance.md").read_text(encoding="utf-8")

    assert "Issue #120" in acceptance
    assert "v0.26.0-preview.1" in acceptance
    assert "manual-pending" in acceptance
    assert "当前记录状态：`manual-pending`" in acceptance
    assert "当前记录状态：`target-accepted`" not in acceptance
    assert "智能填写" in acceptance
    assert "九类任务" in acceptance or "九任务" in acceptance
    assert "单列连续区域" in acceptance or "单列" in acceptance
    assert "失败补偿" in acceptance
