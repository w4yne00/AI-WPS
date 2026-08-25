# Issue #93: publish v0.25.2-alpha candidate identity without rewriting 0.25.1.
import hashlib
import importlib.util
import json
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "packaging/delivery-sources-v0252.json"
BUILD = ROOT / "packaging/build_v0252_delivery_kit.sh"
PREPARE = ROOT / "packaging/prepare_v0252_delivery.py"
AUDIT = ROOT / "packaging/audit_v0252_delivery.py"
STATUS = ROOT / "packaging/v0252-candidate-status.json"
NOTE = ROOT / "packaging/v0252-delivery.md"
ACCEPTANCE = ROOT / "packaging/v0252-target-machine-acceptance.md"
FROZEN_0251 = ROOT / (
    "dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260824-d7a1dd8-v0251.tar.gz"
)
FROZEN_0251_SHA = "ec318db4ffbda499c24aa6fb50958628cc4eaa030b22389bbf29cd783b1adbf6"
FROZEN_0251_BUILD_ID = (
    "AI-WPS-P1-WORD-EXCEL-PPT-0.25.1-20260824-d7a1dd8ef4bd595c0e8611fdfffcf696eebe57f0"
)
REJECTED_DACD1E9 = "ai-wps-phase1-delivery-20260825-dacd1e9-v0252.tar.gz"
REJECTED_DACD1E9_SHA = "c1dfc64fb099c21a8fa05fb64fad4f98d8b7ac5500de052a3f03c3fa8f075871"
REJECTED_DACD1E9_BUILD_ID = (
    "AI-WPS-P1-WORD-EXCEL-PPT-0.25.2-20260825-dacd1e9d0df9b18ca8103d3270f8bf979931cb87"
)
FORBIDDEN_CLAIMS = (
    "图片审查已可用",
    "目标机已验收",
    "wpsAcceptanceConfirmed",
)


def _load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v0251_d7a1dd8_archive_and_sidecar_bytes_stay_frozen():
    # Break: rewriting or replacing the frozen 0.25.1 candidate archive.
    checksum = FROZEN_0251.with_name(FROZEN_0251.name + ".sha256")
    digest = hashlib.sha256(FROZEN_0251.read_bytes()).hexdigest()
    assert digest == FROZEN_0251_SHA
    assert checksum.read_text(encoding="utf-8").split() == [FROZEN_0251_SHA, FROZEN_0251.name]


def test_v0251_status_still_registers_d7a1dd8_as_its_only_candidate():
    # Break: mutating the frozen 0.25.1 lineage so d7a1dd8 is no longer candidate.
    status = json.loads(
        (ROOT / "packaging/v0251-candidate-status.json").read_text(encoding="utf-8")
    )
    current = [record for record in status["records"] if record.get("status") == "candidate"]
    assert status["version"] == "0.25.1-alpha"
    assert current == [
        {
            "candidateBuildId": FROZEN_0251_BUILD_ID,
            "archiveName": FROZEN_0251.name,
            "archiveChecksumFile": FROZEN_0251.name + ".sha256",
            "sourceCommit": "d7a1dd8ef4bd595c0e8611fdfffcf696eebe57f0",
            "archiveSha256": FROZEN_0251_SHA,
            "status": "candidate",
            "recordedAt": "20260824",
        }
    ]


def test_v0252_policy_is_phase1_identity_and_does_not_enter_preview():
    # Break: current delivery policy stays 0.25.1 or ships Preview assets.
    assert POLICY.is_file()
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    assert policy["version"] == "0.25.2-alpha"
    assert policy["basePolicy"] == "delivery-sources-v0251.json"
    entries = {
        (entry["source"], entry["target"])
        for entry in policy["entries"]
        if entry.get("type") == "file"
    }
    assert entries >= {
        ("packaging/v0252-delivery.md", "docs/v0252-delivery.md"),
        (
            "packaging/v0252-target-machine-acceptance.md",
            "docs/v0252-target-machine-acceptance.md",
        ),
        ("packaging/v0252-candidate-status.json", "docs/v0252-candidate-status.json"),
        ("packaging/audit_v0252_delivery.py", "scripts/audit_v0252_delivery.py"),
    }
    dumped = json.dumps(policy["entries"], ensure_ascii=False).lower()
    assert "preview" not in dumped
    assert "material_composer" not in dumped


def test_v0252_build_fail_closes_on_0252_identity_and_0251_baseline():
    # Break: build script still emits v0251 identity or skips 0.25.1 baseline.
    assert BUILD.is_file()
    build = BUILD.read_text(encoding="utf-8")
    for required in (
        "0.25.2-alpha",
        "0.25.1-alpha",
        "AI_WPS_V0251_BASELINE_ARCHIVE",
        "delivery-sources-v0252.json",
        "prepare_v0252_delivery.py",
        "audit_v0252_delivery.py",
        "ai-wps-phase1-delivery-${DATE_TAG}-${SOURCE_TAG}-v0252",
        "--acceptance-issue",
        "59",
        "status=candidate",
        "node --test",
        "check_python38_compatibility.py",
        "python38_delivery_lifecycle_gate.py",
    ):
        assert required in build
    assert "preview" not in build.lower()
    assert "cp -R" not in build


def test_v0252_audit_pins_identity_candidate_and_issue_59_pending():
    # Break: auditor still accepts 0.25.1 or writes target-accepted.
    assert AUDIT.is_file()
    audit = AUDIT.read_text(encoding="utf-8")
    for required in (
        'VERSION = "0.25.2-alpha"',
        'BASELINE_VERSION = "0.25.1-alpha"',
        "ISSUE_59_MANUAL_ACCEPTANCE_REQUIRED",
        "manual-pending",
        "status=candidate",
        "VISUAL_DEFAULT_MUST_BE_OPEN",
        "VISUAL_MUST_NOT_REQUIRE_WPS_ACCEPTANCE",
        "wps-ai-assistant",
        "wps-ai-assistant-et",
        "wps-ai-assistant-wpp",
    ):
        assert required in audit
    assert "target-accepted" not in audit
    assert "requiresWpsAcceptance\") is not False" in audit or (
        "requiresWpsAcceptance" in audit and "False" in audit
    )


def test_v0252_status_does_not_register_d7a1dd8_as_current_candidate():
    # Break: copying the 0.25.1 candidate into the 0.25.2 current slot.
    assert STATUS.is_file()
    status = json.loads(STATUS.read_text(encoding="utf-8"))
    assert status["version"] == "0.25.2-alpha"
    current = [record for record in status.get("records", []) if record.get("status") == "candidate"]
    for record in current:
        assert record.get("archiveName") != FROZEN_0251.name
        assert record.get("candidateBuildId") != FROZEN_0251_BUILD_ID
        assert "0.25.2" in str(record.get("candidateBuildId", ""))


def test_v0252_status_keeps_dacd1e9_rejected_with_frozen_digest():
    # Break: leaving dacd1e9 as the current 0.25.2 candidate after the title-fix rebuild.
    assert STATUS.is_file()
    status = json.loads(STATUS.read_text(encoding="utf-8"))
    records = [
        record
        for record in status.get("records", [])
        if record.get("archiveName") == REJECTED_DACD1E9
    ]
    assert records == [
        {
            "candidateBuildId": REJECTED_DACD1E9_BUILD_ID,
            "archiveName": REJECTED_DACD1E9,
            "archiveChecksumFile": REJECTED_DACD1E9 + ".sha256",
            "sourceCommit": "dacd1e9d0df9b18ca8103d3270f8bf979931cb87",
            "archiveSha256": REJECTED_DACD1E9_SHA,
            "status": "rejected",
            "recordedAt": "20260825",
            "reason": (
                "rejected: PPT structure review could not read Chinese template "
                "titles (标题 1/标题 3) or the section subtitle bar; rebuild "
                "includes that extractor fix"
            ),
        }
    ]
    current = [record for record in status.get("records", []) if record.get("status") == "candidate"]
    for record in current:
        assert record.get("archiveName") != REJECTED_DACD1E9


def test_v0252_docs_describe_defaults_upgrade_and_visual_off_without_overclaim():
    # Break: 0.25.2 docs still describe dormant image semantics or claim acceptance.
    for path in (NOTE, ACCEPTANCE):
        assert path.is_file()
        text = path.read_text(encoding="utf-8")
        for required in (
            "0.25.2-alpha",
            "图像语义补充",
            "manual-pending",
            "Issue #59",
            "视觉关闭降级",
        ):
            assert required in text, "{0} missing {1}".format(path, required)
        for forbidden in FORBIDDEN_CLAIMS:
            assert forbidden not in text, "{0} contains {1}".format(path, forbidden)
        assert "WPS 验收确认" not in text

    note = NOTE.read_text(encoding="utf-8")
    acceptance = ACCEPTANCE.read_text(encoding="utf-8")
    assert "新安装" in note and "默认" in note
    assert "升级" in note
    assert "新安装" in acceptance
    assert "覆盖升级" in acceptance or "升级迁移" in acceptance
    assert "图片语义总开关保持关闭" not in acceptance


def test_current_product_docs_use_v0252_identity_and_keep_frozen_0251_evidence():
    # Break: current-version docs stay on 0.25.1 or drop frozen d7a1dd8 evidence.
    documents = (
        ROOT / "README.md",
        ROOT / "README-ZH.md",
        ROOT / "docs/codex-handoff.md",
    )
    for path in documents:
        text = path.read_text(encoding="utf-8")
        assert "v0.25.2-alpha" in text
        assert FROZEN_0251_SHA in text
        assert "20260824-d7a1dd8" in text
        assert "manual-pending" in text
        for forbidden in FORBIDDEN_CLAIMS:
            assert forbidden not in text
        assert "图像语义补充" in text

    handoff = (ROOT / "docs/codex-handoff.md").read_text(encoding="utf-8")
    assert "当前版本：`v0.25.2-alpha`" in handoff
    readme_zh = (ROOT / "README-ZH.md").read_text(encoding="utf-8")
    assert "| 当前版本 | `v0.25.2-alpha` |" in readme_zh
    readme_en = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "| Version | `v0.25.2-alpha` |" in readme_en


def test_v0252_prepare_rewrites_host_and_adapter_identity_from_0251_predecessor(tmp_path):
    # Break: packaged Word/Excel/PPT/Adapter identity remains 0.25.1-alpha.
    assert PREPARE.is_file()
    delivery = tmp_path / "delivery"
    for relative in (
        "packages/wps-ai-assistant_1.0.0",
        "packages/wps-ai-assistant-et_1.0.0",
        "packages/wps-ai-assistant-wpp_1.0.0",
        "packages/adapter-start-kit/adapter_service/system_prompts",
        "packages/adapter-start-kit/adapter_service/format_rule_packs",
        "packages/adapter-start-kit/config",
        "docs",
        "scripts",
    ):
        (delivery / relative).mkdir(parents=True)

    (delivery / "release-manifest.json").write_text(
        json.dumps(
            {
                "version": "0.25.1-alpha",
                "adapter": {
                    "version": "0.25.1-alpha",
                    "systemPromptManifest": (
                        "packages/adapter-start-kit/adapter_service/system_prompts/manifest.json"
                    ),
                },
                "deliveryPolicy": {"status": "candidate"},
            }
        ),
        encoding="utf-8",
    )
    (delivery / "release-allowlist.json").write_text(
        json.dumps({"version": "0.25.1-alpha", "files": []}), encoding="utf-8"
    )
    (delivery / "packages/adapter-start-kit/adapter_service/system_prompts/manifest.json").write_text(
        json.dumps({"release": "0.25.1-alpha"}), encoding="utf-8"
    )
    (delivery / "format-rule-assets-manifest.json").write_text(
        json.dumps(
            {
                "version": "0.25.1-format-rules-alpha",
                "deliveryVersion": "0.25.1-alpha",
                "rulePack": (
                    "packages/adapter-start-kit/adapter_service/format_rule_packs/"
                    "technical-document-template-rules.v1.0.0.json"
                ),
                "algorithm": {"notice": "unused"},
                "python": {"compatibilityGate": "unused"},
            }
        ),
        encoding="utf-8",
    )
    (
        delivery
        / "packages/adapter-start-kit/adapter_service/format_rule_packs/"
        "technical-document-template-rules.v1.0.0.json"
    ).write_text(json.dumps({"algorithm": {}}), encoding="utf-8")
    for name in (
        "wps-ai-assistant_1.0.0",
        "wps-ai-assistant-et_1.0.0",
        "wps-ai-assistant-wpp_1.0.0",
    ):
        (delivery / "packages" / name / "manifest.json").write_text(
            json.dumps({"name": name, "version": "0.25.1-alpha"}), encoding="utf-8"
        )
        (delivery / "packages" / name / "index.js").write_text(
            'var APP_VERSION = "0.25.1-alpha";\n', encoding="utf-8"
        )
    (delivery / "packages/adapter-start-kit/adapter_service/version.py").write_text(
        'APP_VERSION = "0.25.1-alpha"\n', encoding="utf-8"
    )
    (delivery / "docs/v0252-candidate-status.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "product": "AI-WPS",
                "version": "0.25.2-alpha",
                "records": [],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (delivery / "docs/v0252-delivery.md").write_text("placeholder\n", encoding="utf-8")
    (delivery / "docs/v0252-target-machine-acceptance.md").write_text(
        (ROOT / "packaging/v0252-target-machine-acceptance.md").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (delivery / "scripts/audit_v0252_delivery.py").write_text(
        'VERSION = "0.25.2-alpha"\nBASELINE_VERSION = "0.25.1-alpha"\n',
        encoding="utf-8",
    )
    (delivery / "scripts/python38_delivery_lifecycle_gate.py").write_text(
        'baseline_version = "0.25.1-alpha"\n', encoding="utf-8"
    )

    result = subprocess.run(
        [
            sys.executable,
            str(PREPARE),
            str(delivery),
            "--date",
            "20260825",
            "--baseline-archive",
            str(FROZEN_0251),
            "--previous-candidate-archive",
            str(FROZEN_0251),
            "--baseline-version",
            "0.25.1-alpha",
            "--acceptance-issue",
            "59",
            "--source-commit",
            "abc1234",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    manifest = json.loads((delivery / "release-manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == "0.25.2-alpha"
    assert manifest["adapter"]["version"] == "0.25.2-alpha"
    assert manifest["baseline"]["acceptedVersion"] == "0.25.1-alpha"
    assert manifest["deliveryPolicy"]["status"] == "candidate"
    assert manifest["targetAcceptance"]["status"] == "manual-pending"
    assert manifest["targetAcceptanceIssue"] == 59
    assert manifest["visualPolicy"]["enabledByDefault"] is True
    assert manifest["visualPolicy"]["requiresWpsAcceptance"] is False
    assert manifest["candidateEvidence"]["supersedes"]["archiveName"] == FROZEN_0251.name
    assert manifest["candidateEvidence"]["archiveChecksumFile"].endswith("-abc1234-v0252.tar.gz.sha256")
    for name in (
        "wps-ai-assistant_1.0.0",
        "wps-ai-assistant-et_1.0.0",
        "wps-ai-assistant-wpp_1.0.0",
    ):
        plugin = json.loads(
            (delivery / "packages" / name / "manifest.json").read_text(encoding="utf-8")
        )
        assert plugin["version"] == "0.25.2-alpha"
    assert 'APP_VERSION = "0.25.2-alpha"' in (
        delivery / "packages/adapter-start-kit/adapter_service/version.py"
    ).read_text(encoding="utf-8")
    lineage = json.loads((delivery / "docs/v0252-candidate-status.json").read_text(encoding="utf-8"))
    current = [record for record in lineage["records"] if record.get("status") == "candidate"]
    assert len(current) == 1
    assert current[0]["archiveName"] == "ai-wps-phase1-delivery-20260825-abc1234-v0252.tar.gz"
    assert current[0]["archiveName"] != FROZEN_0251.name
    assert 'APP_VERSION = "0.25.2-alpha"' in (
        delivery / "packages/wps-ai-assistant_1.0.0/index.js"
    ).read_text(encoding="utf-8")
    audit_module = _load_module(AUDIT, "v0252_delivery_audit")
    audit_module.audit_target_acceptance_record(delivery, manifest)


def test_v0252_audit_rejects_stale_0251_packaged_identity(tmp_path):
    # Break: auditor accepts a tree whose version is still 0.25.1-alpha.
    assert AUDIT.is_file()
    module = _load_module(AUDIT, "v0252_delivery_audit")
    (tmp_path / "release-manifest.json").write_text(
        json.dumps(
            {
                "version": "0.25.1-alpha",
                "adapter": {"version": "0.25.1-alpha"},
                "deliveryPolicy": {"status": "candidate"},
                "targetAcceptanceIssue": 59,
                "targetAcceptance": {"status": "manual-pending"},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "release-allowlist.json").write_text(
        json.dumps({"version": "0.25.1-alpha"}), encoding="utf-8"
    )
    with pytest.raises(module.DeliveryFailure, match="V0252_VERSION_MISMATCH"):
        module.audit(tmp_path)
