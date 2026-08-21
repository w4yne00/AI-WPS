import hashlib
import importlib.util
import json
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "packaging/delivery-sources-v0251.json"
BUILD = ROOT / "packaging/build_v0251_delivery_kit.sh"
PREPARE = ROOT / "packaging/prepare_v0251_delivery.py"
AUDIT = ROOT / "packaging/audit_v0251_delivery.py"
LIFECYCLE = ROOT / "packaging/python38_delivery_lifecycle_gate.py"


def load_v0251_audit_module():
    spec = importlib.util.spec_from_file_location("v0251_delivery_audit", AUDIT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v0251_policy_keeps_phase1_baseline_and_excludes_future_work():
    policy = json.loads(POLICY.read_text(encoding="utf-8"))

    assert policy["version"] == "0.25.1-alpha"
    assert policy["basePolicy"] == "delivery-sources-v0250.json"
    entries = json.dumps(policy["entries"], ensure_ascii=False)
    assert "v0251-delivery.md" in entries
    assert "audit_v0251_delivery.py" in entries
    assert "adapter_service/app/core/outline_level.py" in entries
    for excluded in ("material_composer", "ADR-0116", "D-0001", "ADR-0117"):
        assert excluded not in entries


def test_v0251_policy_ships_issue_59_target_acceptance_record():
    policy = json.loads(POLICY.read_text(encoding="utf-8"))

    assert {
        (entry["source"], entry["target"])
        for entry in policy["entries"]
        if entry.get("type") == "file"
    } >= {
        (
            "packaging/v0251-target-machine-acceptance.md",
            "docs/v0251-target-machine-acceptance.md",
        )
    }
    record = (ROOT / "packaging/v0251-target-machine-acceptance.md").read_text(
        encoding="utf-8"
    )
    for required in (
        "Issue #59",
        "60,000",
        "120,000",
        "取消",
        "只读",
        "图片语义",
        "manual-pending",
        "不写入仓库",
        "≤ 30 秒",
        "≤ 60 秒",
        "两遍指纹",
    ):
        assert required in record


def test_v0251_audit_rejects_non_pending_target_acceptance_result(tmp_path):
    audit_module = load_v0251_audit_module()
    record = (ROOT / "packaging/v0251-target-machine-acceptance.md").read_text(
        encoding="utf-8"
    )
    record = record.replace("| `manual-pending` |", "| `passed` |", 1)
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "v0251-target-machine-acceptance.md").write_text(
        record, encoding="utf-8"
    )

    with pytest.raises(
        audit_module.DeliveryFailure,
        match="TARGET_ACCEPTANCE_RECORD_RESULTS_MUST_REMAIN_PENDING",
    ):
        audit_module.audit_target_acceptance_record(
            tmp_path,
            {"targetAcceptanceIssue": 59, "targetAcceptance": {"status": "manual-pending"}},
        )


def test_v0251_build_requires_candidate_baseline_and_all_delivery_gates():
    build = BUILD.read_text(encoding="utf-8")

    for required in (
        "AI_WPS_V0250_BASELINE_ARCHIVE",
        "delivery-sources-v0251.json",
        "prepare_v0251_delivery.py",
        "audit_v0251_delivery.py",
        "0.25.1-alpha",
        "ai-wps-phase1-delivery-${DATE_TAG}-v0251",
        "--acceptance-issue",
        "node --test",
        "check_python38_compatibility.py",
        "python38_delivery_lifecycle_gate.py",
        "sha256",
    ):
        assert required in build
    assert "preview" not in build.lower()
    assert "cp -R" not in build


def test_v0251_audit_requires_release_identity_plugin_cache_and_target_acceptance():
    audit = AUDIT.read_text(encoding="utf-8")

    for required in (
        "0.25.1-alpha",
        "0.25.0-alpha",
        "targetAcceptanceIssue",
        "archiveChecksumFile",
        "sourceCommit",
        "wps-ai-assistant",
        "v0251_delivery_audit=passed",
    ):
        assert required in audit


def test_v0251_lifecycle_gate_uses_manifest_auditor_instead_of_v0250_name():
    lifecycle = LIFECYCLE.read_text(encoding="utf-8")

    assert "deliveryPolicy" in lifecycle
    assert "auditScript" in lifecycle
    assert "audit_v0251_delivery.py" not in lifecycle


def test_v0251_archive_checksum_verification_checks_name_and_digest(tmp_path):
    audit_module = load_v0251_audit_module()
    archive = tmp_path / "ai-wps-phase1-delivery-20260816-v0251.tar.gz"
    checksum = tmp_path / "ai-wps-phase1-delivery-20260816-v0251.tar.gz.sha256"
    archive.write_bytes(b"candidate-archive")
    checksum.write_text(
        "{0}  {1}\n".format(hashlib.sha256(archive.read_bytes()).hexdigest(), archive.name),
        encoding="utf-8",
    )

    audit_module.audit_archive_checksum(archive, checksum, archive.name)
    checksum.write_text("0" * 64 + "  " + archive.name + "\n", encoding="utf-8")
    with pytest.raises(audit_module.DeliveryFailure, match="CHECKSUM_MISMATCH"):
        audit_module.audit_archive_checksum(archive, checksum)


def test_v0251_preparation_records_baseline_evidence_and_removes_old_identity(tmp_path):
    delivery = tmp_path / "delivery"
    (delivery / "packages/adapter-start-kit/adapter_service/system_prompts").mkdir(
        parents=True
    )
    (delivery / "packages/adapter-start-kit/adapter_service/format_rule_packs").mkdir(
        parents=True
    )
    (delivery / "packages/adapter-start-kit/adapter_service/vendor").mkdir(parents=True)
    (delivery / "packages/adapter-start-kit/config").mkdir(parents=True)
    (delivery / "scripts").mkdir(parents=True)
    (delivery / "docs").mkdir(parents=True)
    (delivery / "release-manifest.json").write_text(
        json.dumps(
            {
                "version": "0.25.0-alpha",
                "adapter": {
                    "version": "0.25.0-alpha",
                    "systemPromptManifest": "packages/adapter-start-kit/adapter_service/system_prompts/manifest.json",
                },
                "deliveryPolicy": {"status": "candidate"},
            }
        ),
        encoding="utf-8",
    )
    (delivery / "release-allowlist.json").write_text(
        json.dumps(
            {
                "version": "0.25.0-alpha",
                "files": ["docs/v0250-delivery.md", "scripts/audit_v0250_delivery.py"],
            }
        ),
        encoding="utf-8",
    )
    (delivery / "packages/adapter-start-kit/adapter_service/system_prompts/manifest.json").write_text(
        json.dumps({"release": "0.25.0-alpha"}), encoding="utf-8"
    )
    (delivery / "scripts/audit_v0250_delivery.py").write_text(
        'VERSION = "0.25.0-alpha"\n', encoding="utf-8"
    )
    (delivery / "scripts/audit_v0251_delivery.py").write_text(
        'VERSION = "0.25.1-alpha"\nBASELINE_VERSION = "0.25.0-alpha"\n',
        encoding="utf-8",
    )
    (delivery / "scripts/python38_delivery_lifecycle_gate.py").write_text(
        'baseline_version = "0.25.0-alpha"\n', encoding="utf-8"
    )
    (delivery / "README.md").write_text(
        "v0.25.1-alpha uses the v0.25.0-alpha baseline.\n", encoding="utf-8"
    )
    (delivery / "docs/v0250-delivery.md").write_text("old candidate\n", encoding="utf-8")
    (delivery / "docs/v0251-delivery.md").write_text(
        "v0.25.1-alpha uses v0.25.0-alpha as its baseline.\n", encoding="utf-8"
    )
    (delivery / "format-rule-assets-manifest.json").write_text(
        json.dumps(
            {
                "version": "0.25.0-format-rules-alpha",
                "rulePack": "packages/adapter-start-kit/adapter_service/format_rule_packs/rules.json",
                "algorithm": {
                    "notice": "packages/adapter-start-kit/adapter_service/vendor/THIRD_PARTY_NOTICES.md"
                },
                "python": {"compatibilityGate": "scripts/check_python38_compatibility.py"},
            }
        ),
        encoding="utf-8",
    )
    (delivery / "packages/adapter-start-kit/adapter_service/format_rule_packs/technical-file-format-requirements.v2026-05-23.json").write_text(
        json.dumps({"algorithm": {}}), encoding="utf-8"
    )
    (delivery / "packages/adapter-start-kit/adapter_service/vendor/THIRD_PARTY_NOTICES.md").write_text(
        "notice\n", encoding="utf-8"
    )
    (delivery / "scripts/check_python38_compatibility.py").write_text("# gate\n", encoding="utf-8")

    baseline_root = tmp_path / "baseline"
    baseline_root.mkdir()
    (baseline_root / "release-manifest.json").write_text(
        json.dumps(
            {
                "version": "0.25.0-alpha",
                "deliveryPolicy": {"status": "candidate"},
            }
        ),
        encoding="utf-8",
    )
    baseline = tmp_path / "v0250.tar.gz"
    with tarfile.open(baseline, "w:gz") as archive:
        archive.add(baseline_root, arcname="v0250")

    result = subprocess.run(
        [
            sys.executable,
            str(PREPARE),
            str(delivery),
            "--date",
            "20260816",
            "--baseline-archive",
            str(baseline),
            "--baseline-version",
            "0.25.0-alpha",
            "--acceptance-issue",
            "59",
            "--source-commit",
            "b7a1cf9",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    manifest = json.loads((delivery / "release-manifest.json").read_text())
    assert manifest["version"] == "0.25.1-alpha"
    assert manifest["adapter"]["version"] == "0.25.1-alpha"
    assert manifest["baseline"]["acceptedVersion"] == "0.25.0-alpha"
    assert manifest["targetAcceptanceIssue"] == 59
    assert manifest["targetAcceptance"]["status"] == "manual-pending"
    assert manifest["candidateEvidence"]["sourceCommit"] == "b7a1cf9"
    assert manifest["candidateEvidence"]["archiveChecksumFile"].endswith(
        "v0251.tar.gz.sha256"
    )
    assert not (delivery / "docs/v0250-delivery.md").exists()
    assert not (delivery / "scripts/audit_v0250_delivery.py").exists()
    assert "BASELINE_VERSION = \"0.25.0-alpha\"" in (
        delivery / "scripts/audit_v0251_delivery.py"
    ).read_text(encoding="utf-8")
    assert 'baseline_version = "0.25.0-alpha"' in (
        delivery / "scripts/python38_delivery_lifecycle_gate.py"
    ).read_text(encoding="utf-8")
    assert "v0.25.0-alpha" in (delivery / "README.md").read_text(encoding="utf-8")
    assert "v0.25.0-alpha" in (delivery / "docs/v0251-delivery.md").read_text(
        encoding="utf-8"
    )
    assert "v0250-delivery.md" not in json.dumps(
        json.loads((delivery / "release-allowlist.json").read_text())
    )
    assets = json.loads((delivery / "format-rule-assets-manifest.json").read_text())
    assert assets["version"] == "0.25.1-format-rules-alpha"
    assert assets["deliveryVersion"] == "0.25.1-alpha"
