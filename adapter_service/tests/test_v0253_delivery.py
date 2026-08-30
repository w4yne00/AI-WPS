# Issue #101: publish v0.25.3-alpha candidate identity without rewriting 0.25.2.
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "packaging/delivery-sources-v0253.json"
BUILD = ROOT / "packaging/build_v0253_delivery_kit.sh"
PREPARE = ROOT / "packaging/prepare_v0253_delivery.py"
AUDIT = ROOT / "packaging/audit_v0253_delivery.py"
STATUS = ROOT / "packaging/v0253-candidate-status.json"
NOTE = ROOT / "packaging/v0253-delivery.md"
ACCEPTANCE = ROOT / "packaging/v0253-target-machine-acceptance.md"
FROZEN_0251 = ROOT / (
    "dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260824-d7a1dd8-v0251.tar.gz"
)
FROZEN_0251_SHA = "ec318db4ffbda499c24aa6fb50958628cc4eaa030b22389bbf29cd783b1adbf6"
FROZEN_0251_BUILD_ID = (
    "AI-WPS-P1-WORD-EXCEL-PPT-0.25.1-20260824-d7a1dd8ef4bd595c0e8611fdfffcf696eebe57f0"
)
FROZEN_0252 = ROOT / (
    "dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260825-850871c-v0252.tar.gz"
)
FROZEN_0252_SHA = "c5d663d1249147104bee66790fea60f5e15675418a51c0c1a7a0fc028a285a92"
FROZEN_0252_BUILD_ID = (
    "AI-WPS-P1-WORD-EXCEL-PPT-0.25.2-20260825-850871c10a17f03c8a58abd02ca58c2f3fc70fc9"
)
CURRENT_0253 = "ai-wps-phase1-delivery-20260826-d1a346b-v0253.tar.gz"
CURRENT_0253_SHA = "120a2cfd8decd956224c3702721d85846bdaecf91d71b87b31c0f7be1b258cb7"
CURRENT_0253_BUILD_ID = (
    "AI-WPS-P1-WORD-EXCEL-PPT-0.25.3-20260826-d1a346b0d7e1301f74b37e692664fd31085ee050"
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


def _require_archived_fixture(path):
    if not os.path.lexists(str(path)):
        pytest.skip("archived delivery fixture was removed: {0}".format(path.name))
    assert path.is_file(), "archived delivery fixture is not a regular file: {0}".format(
        path
    )
    return path


def test_v0253_d1a346b_archive_and_sidecar_bytes_match_registered_digest():
    # Break: committing a different tarball than the registered 0.25.3 candidate.
    archive = ROOT / "dist-phase1-delivery-kit" / CURRENT_0253
    assert archive.is_file()
    checksum = archive.with_name(archive.name + ".sha256")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    assert digest == CURRENT_0253_SHA
    assert checksum.read_text(encoding="utf-8").split() == [CURRENT_0253_SHA, CURRENT_0253]


def test_v0252_850871c_archive_and_sidecar_bytes_stay_frozen():
    # Break: rewriting or replacing the frozen 0.25.2 candidate archive.
    _require_archived_fixture(FROZEN_0252)
    checksum = FROZEN_0252.with_name(FROZEN_0252.name + ".sha256")
    digest = hashlib.sha256(FROZEN_0252.read_bytes()).hexdigest()
    assert digest == FROZEN_0252_SHA
    assert checksum.read_text(encoding="utf-8").split() == [FROZEN_0252_SHA, FROZEN_0252.name]


def test_v0252_status_still_registers_850871c_as_its_only_candidate():
    # Break: mutating the frozen 0.25.2 lineage so 850871c is no longer candidate.
    status = json.loads(
        (ROOT / "packaging/v0252-candidate-status.json").read_text(encoding="utf-8")
    )
    current = [record for record in status["records"] if record.get("status") == "candidate"]
    assert status["version"] == "0.25.2-alpha"
    assert current == [
        {
            "candidateBuildId": FROZEN_0252_BUILD_ID,
            "archiveName": FROZEN_0252.name,
            "archiveChecksumFile": FROZEN_0252.name + ".sha256",
            "sourceCommit": "850871c10a17f03c8a58abd02ca58c2f3fc70fc9",
            "archiveSha256": FROZEN_0252_SHA,
            "status": "candidate",
            "recordedAt": "20260825",
        }
    ]


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


def test_v0253_policy_is_phase1_identity_and_does_not_enter_preview():
    # Break: current delivery policy stays 0.25.2 or ships Preview assets.
    assert POLICY.is_file()
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    assert policy["version"] == "0.25.3-alpha"
    assert policy["basePolicy"] == "delivery-sources-v0252.json"
    entries = {
        (entry["source"], entry["target"])
        for entry in policy["entries"]
        if entry.get("type") == "file"
    }
    assert entries >= {
        ("packaging/v0253-delivery.md", "docs/v0253-delivery.md"),
        (
            "packaging/v0253-target-machine-acceptance.md",
            "docs/v0253-target-machine-acceptance.md",
        ),
        ("packaging/v0253-candidate-status.json", "docs/v0253-candidate-status.json"),
        ("packaging/audit_v0253_delivery.py", "scripts/audit_v0253_delivery.py"),
    }
    dumped = json.dumps(policy["entries"], ensure_ascii=False).lower()
    assert "preview" not in dumped
    assert "material_composer" not in dumped


def test_v0253_build_fail_closes_on_0253_identity_and_0252_baseline():
    # Break: build script still emits v0252 identity or skips 0.25.2 baseline.
    assert BUILD.is_file()
    build = BUILD.read_text(encoding="utf-8")
    for required in (
        "0.25.3-alpha",
        "0.25.2-alpha",
        "AI_WPS_V0252_BASELINE_ARCHIVE",
        "delivery-sources-v0253.json",
        "prepare_v0253_delivery.py",
        "audit_v0253_delivery.py",
        "ai-wps-phase1-delivery-${DATE_TAG}-${SOURCE_TAG}-v0253",
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


def test_v0253_audit_pins_identity_candidate_and_issue_59_pending():
    # Break: auditor still accepts 0.25.2 or writes target-accepted.
    assert AUDIT.is_file()
    audit = AUDIT.read_text(encoding="utf-8")
    for required in (
        'VERSION = "0.25.3-alpha"',
        'BASELINE_VERSION = "0.25.2-alpha"',
        "ISSUE_59_MANUAL_ACCEPTANCE_REQUIRED",
        "manual-pending",
        "status=candidate",
        "VISUAL_DEFAULT_MUST_BE_OPEN",
        "VISUAL_MUST_NOT_REQUIRE_WPS_ACCEPTANCE",
        "wps-ai-assistant",
        "wps-ai-assistant-et",
        "wps-ai-assistant-wpp",
        "结果预览",
        "题注关联结论",
        "幻灯片页角色",
        "AI-WPS-P1-WORD-EXCEL-PPT-0.25.3-",
        "0.25.2-alpha",
    ):
        assert required in audit
    assert "AI-WPS-P1-WORD-EXCEL-PPT-0.25.2-{0}" not in audit
    assert 'or "0.25.2-alpha" in content' in audit
    assert "target-accepted" not in audit
    assert "requiresWpsAcceptance\") is not False" in audit or (
        "requiresWpsAcceptance" in audit and "False" in audit
    )


def test_v0253_status_does_not_register_850871c_as_current_candidate():
    # Break: copying the 0.25.2 candidate into the 0.25.3 current slot.
    assert STATUS.is_file()
    status = json.loads(STATUS.read_text(encoding="utf-8"))
    assert status["version"] == "0.25.3-alpha"
    current = [record for record in status.get("records", []) if record.get("status") == "candidate"]
    for record in current:
        assert record.get("archiveName") != FROZEN_0252.name
        assert record.get("candidateBuildId") != FROZEN_0252_BUILD_ID
        assert "0.25.3" in str(record.get("candidateBuildId", ""))


def test_v0253_status_registers_d1a346b_as_its_only_candidate():
    # Break: leaving 0.25.3 without a unique candidate after the Kylin gate.
    assert STATUS.is_file()
    status = json.loads(STATUS.read_text(encoding="utf-8"))
    current = [record for record in status.get("records", []) if record.get("status") == "candidate"]
    assert current == [
        {
            "candidateBuildId": CURRENT_0253_BUILD_ID,
            "archiveName": CURRENT_0253,
            "archiveChecksumFile": CURRENT_0253 + ".sha256",
            "sourceCommit": "d1a346b0d7e1301f74b37e692664fd31085ee050",
            "archiveSha256": CURRENT_0253_SHA,
            "status": "candidate",
            "recordedAt": "20260826",
        }
    ]


def test_v0253_docs_describe_preview_cards_and_page_roles_without_overclaim():
    # Break: 0.25.3 docs omit #101 capabilities or claim acceptance.
    for path in (NOTE, ACCEPTANCE):
        assert path.is_file()
        text = path.read_text(encoding="utf-8")
        for required in (
            "0.25.3-alpha",
            "结果预览",
            "格式问题",
            "题注关联结论",
            "幻灯片页角色",
            "manual-pending",
            "Issue #59",
            "图像语义补充",
        ):
            assert required in text, "{0} missing {1}".format(path, required)
        for forbidden in FORBIDDEN_CLAIMS:
            assert forbidden not in text, "{0} contains {1}".format(path, forbidden)
        assert "WPS 验收确认" not in text


def test_current_product_docs_use_v0253_identity_and_keep_frozen_0252_evidence():
    # Break: current-version docs stay on 0.25.2 or drop frozen 850871c evidence.
    documents = (
        ROOT / "README.md",
        ROOT / "README-ZH.md",
        ROOT / "docs/codex-handoff.md",
    )
    for path in documents:
        text = path.read_text(encoding="utf-8")
        assert "v0.25.3-alpha" in text
        assert FROZEN_0252_SHA in text
        assert "20260825-850871c" in text
        assert CURRENT_0253_SHA in text
        assert "20260826-d1a346b" in text
        assert FROZEN_0251_SHA in text
        assert "20260824-d7a1dd8" in text
        assert "manual-pending" in text
        for forbidden in FORBIDDEN_CLAIMS:
            assert forbidden not in text
        assert "图像语义补充" in text
        assert "结果预览" in text or "页角色" in text

    handoff = (ROOT / "docs/codex-handoff.md").read_text(encoding="utf-8")
    assert "当前版本：`v0.25.3-alpha`" in handoff
    readme_zh = (ROOT / "README-ZH.md").read_text(encoding="utf-8")
    assert "| 当前版本 | `v0.25.3-alpha` |" in readme_zh
    readme_en = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "| Version | `v0.25.3-alpha` |" in readme_en


def test_v0253_prepare_rewrites_host_and_adapter_identity_from_0252_predecessor(tmp_path):
    # Break: packaged Word/Excel/PPT/Adapter identity remains 0.25.2-alpha.
    assert PREPARE.is_file()
    _require_archived_fixture(FROZEN_0252)
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
                "version": "0.25.2-alpha",
                "adapter": {
                    "version": "0.25.2-alpha",
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
        json.dumps({"version": "0.25.2-alpha", "files": []}), encoding="utf-8"
    )
    (delivery / "packages/adapter-start-kit/adapter_service/system_prompts/manifest.json").write_text(
        json.dumps({"release": "0.25.2-alpha"}), encoding="utf-8"
    )
    (delivery / "format-rule-assets-manifest.json").write_text(
        json.dumps(
            {
                "version": "0.25.1-format-rules-alpha",
                "deliveryVersion": "0.25.2-alpha",
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
            json.dumps({"name": name, "version": "0.25.2-alpha"}), encoding="utf-8"
        )
        (delivery / "packages" / name / "index.js").write_text(
            'var APP_VERSION = "0.25.2-alpha";\n', encoding="utf-8"
        )
    (delivery / "packages/adapter-start-kit/adapter_service/version.py").write_text(
        'APP_VERSION = "0.25.2-alpha"\n', encoding="utf-8"
    )
    (delivery / "docs/v0253-candidate-status.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "product": "AI-WPS",
                "version": "0.25.3-alpha",
                "records": [],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (delivery / "docs/v0253-delivery.md").write_text("placeholder\n", encoding="utf-8")
    (delivery / "docs/v0253-target-machine-acceptance.md").write_text(
        (ROOT / "packaging/v0253-target-machine-acceptance.md").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (delivery / "scripts/audit_v0253_delivery.py").write_text(
        'VERSION = "0.25.3-alpha"\nBASELINE_VERSION = "0.25.2-alpha"\n',
        encoding="utf-8",
    )
    (delivery / "scripts/python38_delivery_lifecycle_gate.py").write_text(
        'baseline_version = "0.25.2-alpha"\n', encoding="utf-8"
    )

    result = subprocess.run(
        [
            sys.executable,
            str(PREPARE),
            str(delivery),
            "--date",
            "20260826",
            "--baseline-archive",
            str(FROZEN_0252),
            "--previous-candidate-archive",
            str(FROZEN_0252),
            "--baseline-version",
            "0.25.2-alpha",
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
    assert manifest["version"] == "0.25.3-alpha"
    assert manifest["adapter"]["version"] == "0.25.3-alpha"
    assert manifest["baseline"]["acceptedVersion"] == "0.25.2-alpha"
    assert manifest["deliveryPolicy"]["status"] == "candidate"
    assert manifest["targetAcceptance"]["status"] == "manual-pending"
    assert manifest["targetAcceptanceIssue"] == 59
    assert manifest["visualPolicy"]["enabledByDefault"] is True
    assert manifest["visualPolicy"]["requiresWpsAcceptance"] is False
    assert manifest["candidateEvidence"]["supersedes"]["archiveName"] == FROZEN_0252.name
    assert manifest["candidateEvidence"]["archiveChecksumFile"].endswith("-abc1234-v0253.tar.gz.sha256")
    for name in (
        "wps-ai-assistant_1.0.0",
        "wps-ai-assistant-et_1.0.0",
        "wps-ai-assistant-wpp_1.0.0",
    ):
        plugin = json.loads(
            (delivery / "packages" / name / "manifest.json").read_text(encoding="utf-8")
        )
        assert plugin["version"] == "0.25.3-alpha"
    assert 'APP_VERSION = "0.25.3-alpha"' in (
        delivery / "packages/adapter-start-kit/adapter_service/version.py"
    ).read_text(encoding="utf-8")
    lineage = json.loads((delivery / "docs/v0253-candidate-status.json").read_text(encoding="utf-8"))
    current = [record for record in lineage["records"] if record.get("status") == "candidate"]
    assert len(current) == 1
    assert current[0]["archiveName"] == "ai-wps-phase1-delivery-20260826-abc1234-v0253.tar.gz"
    assert current[0]["archiveName"] != FROZEN_0252.name
    assert 'APP_VERSION = "0.25.3-alpha"' in (
        delivery / "packages/wps-ai-assistant_1.0.0/index.js"
    ).read_text(encoding="utf-8")
    audit_module = _load_module(AUDIT, "v0253_delivery_audit")
    audit_module.audit_target_acceptance_record(delivery, manifest)
    audit_module.audit_candidate_lineage(delivery, manifest)
    audit_module.audit_candidate_note(delivery, manifest)
    generated_note = (delivery / "docs/v0253-delivery.md").read_text(encoding="utf-8")
    for required in ("结果预览", "格式问题", "题注关联结论", "幻灯片页角色"):
        assert required in generated_note


def test_v0253_audit_rejects_stale_0252_packaged_identity(tmp_path):
    # Break: auditor accepts a tree whose version is still 0.25.2-alpha.
    assert AUDIT.is_file()
    module = _load_module(AUDIT, "v0253_delivery_audit")
    (tmp_path / "release-manifest.json").write_text(
        json.dumps(
            {
                "version": "0.25.2-alpha",
                "adapter": {"version": "0.25.2-alpha"},
                "deliveryPolicy": {"status": "candidate"},
                "targetAcceptanceIssue": 59,
                "targetAcceptance": {"status": "manual-pending"},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "release-allowlist.json").write_text(
        json.dumps({"version": "0.25.2-alpha"}), encoding="utf-8"
    )
    with pytest.raises(module.DeliveryFailure, match="V0253_VERSION_MISMATCH"):
        module.audit(tmp_path)
