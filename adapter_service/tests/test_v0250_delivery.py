import json
import subprocess
import sys
import tarfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "packaging/delivery-sources-v0250.json"
BUILD = ROOT / "packaging/build_v0250_delivery_kit.sh"
PREPARE = ROOT / "packaging/prepare_v0250_delivery.py"
AUDIT = ROOT / "packaging/audit_v0250_delivery.py"
RUNTIME_GATE = ROOT / "packaging/python38_delivery_runtime_gate.py"


def test_v0250_policy_extends_v0240_and_contains_final_runtime_assets():
    policy = json.loads(POLICY.read_text(encoding="utf-8"))

    assert policy["version"] == "0.25.0-alpha"
    assert policy["basePolicy"] == "delivery-sources-v0240.json"
    entries = json.dumps(policy["entries"], ensure_ascii=False)
    for required in (
        "deterministic_format_review.py",
        "format_semantics.py",
        "image_semantics.py",
        "authorized_format_algorithm.py",
        "format_rule_pack.py",
        "wx_doc_format_algorithm",
        "format-semantics-text-v1.yml",
        "format-semantics-vision-v1.yml",
        "THIRD_PARTY_NOTICES.md",
    ):
        assert required in entries


def test_v0250_build_requires_v0240_baseline_and_runs_final_gates():
    build = BUILD.read_text(encoding="utf-8")

    for required in (
        "AI_WPS_V0240_BASELINE_ARCHIVE",
        "delivery-sources-v0250.json",
        "prepare_v0250_delivery.py",
        "audit_v0250_delivery.py",
        "0.25.0-alpha",
        "--baseline-version",
        "status=candidate",
        "node --test",
    ):
        assert required in build
    assert "cp -R" not in build


def test_v0250_audit_and_runtime_gate_enforce_acceptance_and_public_api():
    audit = AUDIT.read_text(encoding="utf-8")
    runtime_gate = RUNTIME_GATE.read_text(encoding="utf-8")

    assert 'baseline.get("acceptanceStateRequired") != "closed"' in audit
    assert "PUBLIC_FORMAT_REVIEW_API_CONTRACT_INVALID" in runtime_gate


def test_v0250_preparation_records_accepted_baseline(tmp_path):
    delivery = tmp_path / "delivery"
    (delivery / "packages/adapter-start-kit/adapter_service/system_prompts").mkdir(
        parents=True
    )
    (delivery / "packages/adapter-start-kit/config").mkdir(parents=True)
    (delivery / "release-manifest.json").write_text(
        json.dumps(
            {
                "version": "0.24.0-alpha",
                "adapter": {
                    "version": "0.24.0-alpha",
                    "systemPromptManifest": "packages/adapter-start-kit/adapter_service/system_prompts/manifest.json",
                },
                "deliveryPolicy": {"status": "candidate"},
            }
        ),
        encoding="utf-8",
    )
    (delivery / "release-allowlist.json").write_text(
        json.dumps({"version": "0.24.0-alpha"}), encoding="utf-8"
    )
    (delivery / "packages/adapter-start-kit/adapter_service/system_prompts/manifest.json").write_text(
        json.dumps({"release": "0.24.0-alpha"}), encoding="utf-8"
    )
    (delivery / "scripts").mkdir(parents=True)
    (delivery / "scripts/audit_v0250_delivery.py").write_text(
        'VERSION = "0.25.0-alpha"\nBASELINE_VERSION = "0.24.0-alpha"\n',
        encoding="utf-8",
    )
    (delivery / "format-rule-assets-manifest.json").write_text(
        json.dumps(
            {
                "version": "0.25.0-format-rules-alpha",
                "rulePack": "adapter_service/format_rule_packs/rules.json",
                "algorithm": {
                    "notice": "adapter_service/vendor/THIRD_PARTY_NOTICES.md"
                },
                "python": {"compatibilityGate": "packaging/check_python38_compatibility.py"},
            }
        ),
        encoding="utf-8",
    )
    (delivery / "packages/adapter-start-kit/adapter_service/format_rule_packs").mkdir(
        parents=True
    )
    (delivery / "packages/adapter-start-kit/adapter_service/format_rule_packs/technical-file-format-requirements.v2026-05-23.json").write_text(
        json.dumps({"algorithm": {}}), encoding="utf-8"
    )
    baseline_root = tmp_path / "baseline"
    baseline_root.mkdir()
    (baseline_root / "release-manifest.json").write_text(
        json.dumps(
            {
                "version": "0.24.0-alpha",
                "deliveryPolicy": {"status": "candidate"},
            }
        ),
        encoding="utf-8",
    )
    baseline = tmp_path / "v0240.tar.gz"
    with tarfile.open(baseline, "w:gz") as archive:
        archive.add(baseline_root, arcname="v0240")

    result = subprocess.run(
        [
            sys.executable,
            str(PREPARE),
            str(delivery),
            "--date",
            "20260814",
            "--baseline-archive",
            str(baseline),
            "--baseline-version",
            "0.24.0-alpha",
            "--acceptance-issue",
            "42",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    manifest = json.loads((delivery / "release-manifest.json").read_text())
    assert manifest["version"] == "0.25.0-alpha"
    assert manifest["adapter"]["version"] == "0.25.0-alpha"
    assert manifest["baseline"]["acceptedVersion"] == "0.24.0-alpha"
    assert manifest["baseline"]["acceptanceIssue"] == 42
    assert manifest["baseline"]["acceptanceStateRequired"] == "closed"
    assert manifest["visualPolicy"]["enabledByDefault"] is False
    assert manifest["formatReview"]["enabledByDefault"] is False
    audit_script = (delivery / "scripts/audit_v0250_delivery.py").read_text()
    assert 'BASELINE_VERSION = "0.24.0-alpha"' in audit_script
    assets = json.loads((delivery / "format-rule-assets-manifest.json").read_text())
    assert assets["rulePack"].startswith("packages/adapter-start-kit/")
