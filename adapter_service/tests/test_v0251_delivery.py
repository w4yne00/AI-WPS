import hashlib
import importlib.util
import json
import re
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

_SYNC_BACKEND_RESULT_CLAIM_RE = re.compile(
    r"(?P<first>同步|后台)(?:入口|的\s*入口)?\s*"
    r"(?:/|和|与|、|及)\s*"
    r"(?P<second>同步|后台)"
    r"(?:入口(?:\s*的)?|的(?:\s*入口)?)?\s*"
    r"(?:格式审查)?\s*结果\s*(?:一致(?:性)?|相同)"
)
_REJECTED_CANDIDATES_RE = re.compile(
    r"`v0\.25\.1-alpha` 已将 (?P<candidates>.*?) 登记为 `rejected`"
)


def _has_sync_backend_result_claim(text):
    return any(
        {match.group("first"), match.group("second")} == {"同步", "后台"}
        for match in _SYNC_BACKEND_RESULT_CLAIM_RE.finditer(text)
    )


def _rejected_candidates_from_validation_section(validation):
    match = _REJECTED_CANDIDATES_RE.search(validation)
    if match is None:
        return set()
    return set(re.findall(r"`([^`]+)`", match.group("candidates")))


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
    assert "v0251-candidate-status.json" in entries
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
        "OutlineLevel=0",
        "OutlineLevel=10",
        "OutlineLevel=1..9",
        "insufficientReason",
        "contentSha256",
        "jobId",
        "表格/嵌套表格",
        "图片元数据",
        "非 BMP emoji",
        "pixelExportCount=0",
        "pixelUploadCount=0",
        "四项指标 JS/Python 对拍",
        "合法输入应无 409",
        "合法输入应启动并记录 `jobId`",
    ):
        assert required in record

    delivery = (ROOT / "packaging/v0251-delivery.md").read_text(encoding="utf-8")
    assert "POST /word/format-review" in delivery
    assert "410 WORD_FORMAT_REVIEW_SYNC_RETIRED" in delivery
    assert "word.format_review.snapshot.v2" in delivery
    assert "分别执行同步和后台格式审查" not in delivery


@pytest.mark.parametrize(
    "claim",
    (
        "同步/后台入口结果一致",
        "同步入口与后台入口结果一致",
        "后台与同步入口结果一致",
        "同步与后台入口结果相同",
        "同步与后台的结果一致",
        "同步与后台入口结果一致性",
        "同步和后台格式审查结果一致",
    ),
)
def test_v0251_delivery_rejects_contradictory_sync_backend_result_claims(claim):
    delivery = (ROOT / "packaging/v0251-delivery.md").read_text(encoding="utf-8")

    assert _has_sync_backend_result_claim(claim)
    assert not _has_sync_backend_result_claim(delivery)


def test_v0251_delivery_separates_sync_retirement_from_v2_hash_acceptance():
    delivery = (ROOT / "packaging/v0251-delivery.md").read_text(encoding="utf-8")

    sync_boundary = (
        "退役同步路由 `POST /word/format-review` 固定返回 "
        "`410 WORD_FORMAT_REVIEW_SYNC_RETIRED` 且不执行审查"
    )
    v2_boundary = (
        "结构/格式哈希、OutlineLevel 和格式事实验收只通过 "
        "`word.format_review.snapshot.v2` 的 snapshot/batch/job v2 后台路径执行"
    )
    lifecycle_boundary = (
        "独立验证 `word.format_review.snapshot.v2` 的 snapshot/batch/job "
        "取消、失败和重启生命周期"
    )
    assert sync_boundary in delivery
    assert v2_boundary in delivery
    assert lifecycle_boundary in delivery


def test_v0251_handoff_rejected_list_contains_latest_candidate_in_validation_context():
    handoff = (ROOT / "docs/codex-handoff.md").read_text(encoding="utf-8")

    validation = handoff.split("## 6. 验证状态", 1)[1].split("## 7. 目标机验证建议", 1)[0]
    rejected_candidates = _rejected_candidates_from_validation_section(validation)
    assert "20260824-ccad09f" in rejected_candidates
    assert "20260824-2e7a3e6" in rejected_candidates
    assert "20260822-e43dc8c" in rejected_candidates

    candidate_only = (
        "`v0.25.1-alpha` 已将 `20260824-ccad09f` 登记为 `candidate`。"
    )
    assert _rejected_candidates_from_validation_section(candidate_only) == set()


def test_v0251_handoff_uses_current_candidate_as_previous_archive_example():
    handoff = (ROOT / "docs/codex-handoff.md").read_text(encoding="utf-8")

    assert (
        "AI_WPS_V0251_PREVIOUS_CANDIDATE_ARCHIVE="
        "dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260824-2e7a3e6-v0251.tar.gz"
    ) in handoff
    assert "AI_WPS_V0251_PREVIOUS_CANDIDATE_ARCHIVE=dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260822-e43dc8c-v0251.tar.gz" not in handoff


def test_v0251_current_candidate_identity_is_consistent_across_release_docs():
    status = json.loads(
        (ROOT / "packaging/v0251-candidate-status.json").read_text(encoding="utf-8")
    )
    expected = {
        "candidateBuildId": "AI-WPS-P1-WORD-EXCEL-PPT-0.25.1-20260824-2e7a3e6b18aa5d297edd8c66b1475c53b3f4b06f",
        "archiveName": "ai-wps-phase1-delivery-20260824-2e7a3e6-v0251.tar.gz",
        "archiveChecksumFile": "ai-wps-phase1-delivery-20260824-2e7a3e6-v0251.tar.gz.sha256",
        "archiveSha256": "576ad6580fc261e486adb3bac784d2e2a7f47c4f62209686bb1e2e58b5599c1e",
        "sourceCommit": "2e7a3e6b18aa5d297edd8c66b1475c53b3f4b06f",
        "status": "rejected",
        "recordedAt": "20260824",
        "reason": "rejected: package delivery note was stale (包内交付说明过期) and missing outline facts were serialized as null (缺失大纲事实被写为 null); repair continues and a new candidate must be rebuilt",
    }
    assert status["records"][-1] == expected

    rejected = status["records"][-2]
    assert rejected["candidateBuildId"].endswith("-ccad09fb1d8019da3a40f14610ab3bd75de1ec23")
    assert rejected["archiveSha256"] == "2c3f8b5004c40fb7271a6afe7e4c8a292acb227b9d3ec08afc7f6b561d413a02"
    assert rejected["status"] == "rejected"

    identity = (
        "20260824-2e7a3e6",
        expected["candidateBuildId"],
        expected["sourceCommit"],
        expected["archiveName"],
        expected["archiveSha256"],
        "Issue #59",
    )
    documents = (
        ROOT / "README.md",
        ROOT / "README-ZH.md",
        ROOT / "docs/codex-handoff.md",
        ROOT / "packaging/v0251-delivery.md",
    )
    for path in documents:
        text = path.read_text(encoding="utf-8")
        for value in identity:
            assert value in text, "{} missing {}".format(path, value)

    validation_documents = documents[:3]
    for path in validation_documents:
        text = path.read_text(encoding="utf-8")
        delivery_lines = [
            line
            for line in text.splitlines()
            if "delivery assertions" in line or "交付断言" in line
        ]
        plugin_lines = [
            line
            for line in text.splitlines()
            if "Formal plugin contract tests" in line
            or "正式插件合同测试" in line
            or "正式插件契约" in line
        ]
        assert any("`23 passed`" in line for line in delivery_lines)
        assert all("`22 passed`" not in line for line in delivery_lines)
        assert any("`22/22`" in line for line in plugin_lines)
        assert all("`22 passed`" not in line for line in plugin_lines)

    for stale in (
        "No new archive has been built",
        "尚未构建新归档",
        "new candidate archive remains pending build",
        "新候选待构建",
        "新候选尚未构建",
        "完成核验后再形成新候选",
        "当前修复构建只接受完整 `HEAD`",
        "当前源码正在修复",
        "source repair is in progress",
    ):
        for path in documents:
            assert stale not in path.read_text(encoding="utf-8")


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


def test_v0251_audit_requires_rejected_previous_candidate_lineage(tmp_path):
    audit_module = load_v0251_audit_module()
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "v0251-candidate-status.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "product": "AI-WPS",
                "version": "0.25.1-alpha",
                "records": [
                    {
                        "candidateBuildId": "AI-WPS-P1-WORD-EXCEL-PPT-0.25.1-20260822-b7a1cf9",
                        "archiveName": "ai-wps-phase1-delivery-20260822-b7a1cf9-v0251.tar.gz",
                        "archiveChecksumFile": "ai-wps-phase1-delivery-20260822-b7a1cf9-v0251.tar.gz.sha256",
                        "status": "candidate",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    manifest = {
        "releaseDate": "20260822",
        "versionRule": "AI-WPS-P1-WORD-EXCEL-PPT-0.25.1-20260822",
        "candidateEvidence": {
            "candidateBuildId": "AI-WPS-P1-WORD-EXCEL-PPT-0.25.1-20260822-b7a1cf9",
            "sourceCommit": "b7a1cf9",
            "archiveChecksumFile": "ai-wps-phase1-delivery-20260822-b7a1cf9-v0251.tar.gz.sha256",
            "automatedResult": "candidate",
            "supersedes": {
                "candidateBuildId": "AI-WPS-P1-WORD-EXCEL-PPT-0.25.1-20260816",
                "archiveName": "ai-wps-phase1-delivery-20260816-v0251.tar.gz",
                "archiveSha256": "1" * 64,
                "status": "rejected",
            },
        },
    }

    with pytest.raises(
        audit_module.DeliveryFailure,
        match="V0251_REJECTED_CANDIDATE_RECORD_MISSING",
    ):
        audit_module.audit_candidate_lineage(tmp_path, manifest)

    manifest["candidateEvidence"]["automatedResult"] = "target-accepted"
    with pytest.raises(
        audit_module.DeliveryFailure,
        match="V0251_AUTOMATED_RESULT_MUST_REMAIN_CANDIDATE",
    ):
        audit_module.audit_candidate_lineage(tmp_path, manifest)


def test_v0251_prepare_rejects_non_calendar_date(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(PREPARE),
            str(tmp_path),
            "--date",
            "20261399",
            "--baseline-archive",
            str(tmp_path / "baseline.tar.gz"),
            "--previous-candidate-archive",
            str(tmp_path / "previous.tar.gz"),
            "--source-commit",
            "b7a1cf9",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "V0251_DATE_INVALID" in result.stdout


def test_v0251_build_requires_candidate_baseline_and_all_delivery_gates():
    build = BUILD.read_text(encoding="utf-8")

    for required in (
        "AI_WPS_V0250_BASELINE_ARCHIVE",
        "AI_WPS_V0251_PREVIOUS_CANDIDATE_ARCHIVE",
        "delivery-sources-v0251.json",
        "prepare_v0251_delivery.py",
        "audit_v0251_delivery.py",
        "0.25.1-alpha",
        "ai-wps-phase1-delivery-${DATE_TAG}-${SOURCE_TAG}-v0251",
        "--acceptance-issue",
        "--previous-candidate-archive",
        "node --test",
        "check_python38_compatibility.py",
        "python38_delivery_lifecycle_gate.py",
        "PYTHONDONTWRITEBYTECODE=1",
        "sha256",
        'AI_WPS_HASH_CONTRACT_PYTHON="$PYTHON_BIN" node --test',
    ):
        assert required in build
    assert "preview" not in build.lower()
    assert "cp -R" not in build


def test_v0251_hash_contract_gate_is_fail_closed_and_discovered_by_provenance():
    build = BUILD.read_text(encoding="utf-8")
    contract_test = ROOT / "formal-plugin-kit/tests/format-review-hash-contract.test.js"

    assert contract_test.is_file()
    assert 'AI_WPS_HASH_CONTRACT_PYTHON="$PYTHON_BIN" node --test' in build
    assert "skip" not in contract_test.read_text(encoding="utf-8").lower()
    assert "AI_WPS_HASH_CONTRACT_PYTHON" in contract_test.read_text(encoding="utf-8")


def test_v0251_rebuild_records_rejected_candidate_and_independent_build_identity():
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    entries = {
        (entry["source"], entry["target"])
        for entry in policy["entries"]
        if entry.get("type") == "file"
    }
    assert (
        "packaging/v0251-candidate-status.json",
        "docs/v0251-candidate-status.json",
    ) in entries

    status = json.loads(
        (ROOT / "packaging/v0251-candidate-status.json").read_text(encoding="utf-8")
    )
    previous = status["records"][0]
    assert previous["status"] == "rejected"
    assert previous["archiveName"] == "ai-wps-phase1-delivery-20260816-v0251.tar.gz"
    assert len(previous["archiveSha256"]) == 64
    for record in status["records"]:
        source_commit = record.get("sourceCommit")
        if source_commit:
            assert record["candidateBuildId"].endswith("-" + source_commit)

    build = BUILD.read_text(encoding="utf-8")
    assert "AI_WPS_V0251_PREVIOUS_CANDIDATE_ARCHIVE" in build
    assert "--previous-candidate-archive" in build

    prepare = PREPARE.read_text(encoding="utf-8")
    assert "candidateBuildId" in prepare
    assert "rejected" in prepare


def test_v0251_audit_requires_release_identity_plugin_cache_and_target_acceptance():
    audit = AUDIT.read_text(encoding="utf-8")

    for required in (
        "0.25.1-alpha",
        "0.25.0-alpha",
        "targetAcceptanceIssue",
        "archiveChecksumFile",
        "sourceCommit",
        "candidateBuildId",
        "supersedes",
        "audit_candidate_lineage",
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
    (delivery / "docs/v0251-candidate-status.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "product": "AI-WPS",
                "version": "0.25.1-alpha",
                "records": [
                    {
                        "candidateBuildId": "AI-WPS-P1-WORD-EXCEL-PPT-0.25.1-20260822",
                        "archiveName": "ai-wps-phase1-delivery-20260822-v0251.tar.gz",
                        "archiveSha256": "0" * 64,
                        "status": "rejected",
                    }
                ],
            }
        ),
        encoding="utf-8",
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
    (delivery / "packages/adapter-start-kit/adapter_service/format_rule_packs/technical-document-template-rules.v1.0.0.json").write_text(
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

    previous_root = tmp_path / "previous"
    previous_root.mkdir()
    (previous_root / "release-manifest.json").write_text(
        json.dumps(
            {
                "version": "0.25.1-alpha",
                "releaseDate": "20260822",
                "versionRule": "AI-WPS-P1-WORD-EXCEL-PPT-0.25.1-20260822",
                "deliveryPolicy": {"status": "candidate"},
            }
        ),
        encoding="utf-8",
    )
    previous = tmp_path / "ai-wps-phase1-delivery-20260822-v0251.tar.gz"
    with tarfile.open(previous, "w:gz") as archive:
        archive.add(previous_root, arcname="old-v0251")
    previous_digest = hashlib.sha256(previous.read_bytes()).hexdigest()
    status_path = delivery / "docs/v0251-candidate-status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status["records"][0]["archiveSha256"] = previous_digest
    status_path.write_text(json.dumps(status), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(PREPARE),
            str(delivery),
            "--date",
            "20260822",
            "--baseline-archive",
            str(baseline),
            "--previous-candidate-archive",
            str(previous),
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
    assert manifest["formatReview"]["enabledByDefault"] is True
    assert manifest["candidateEvidence"]["sourceCommit"] == "b7a1cf9"
    assert manifest["candidateEvidence"]["candidateBuildId"].endswith("-b7a1cf9")
    assert manifest["candidateEvidence"]["supersedes"]["status"] == "rejected"
    assert manifest["candidateEvidence"]["archiveChecksumFile"].endswith(
        "-b7a1cf9-v0251.tar.gz.sha256"
    )
    current = json.loads(status_path.read_text(encoding="utf-8"))["records"][-1]
    assert current["archiveName"] == (
        "ai-wps-phase1-delivery-20260822-b7a1cf9-v0251.tar.gz"
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
    lineage = json.loads(status_path.read_text(encoding="utf-8"))
    assert [record["status"] for record in lineage["records"]] == ["rejected", "candidate"]


def test_v0251_prepare_rewrites_delivery_note_with_current_candidate_identity(tmp_path):
    note = tmp_path / "docs/v0251-delivery.md"
    note.parent.mkdir(parents=True)
    note.write_text("新候选待构建；当前源码修复中。", encoding="utf-8")

    prepare_module = importlib.util.spec_from_file_location("v0251_delivery_prepare", PREPARE)
    assert prepare_module is not None and prepare_module.loader is not None
    module = importlib.util.module_from_spec(prepare_module)
    prepare_module.loader.exec_module(module)
    module.write_candidate_delivery_note(
        tmp_path,
        "20260824",
        "2e7a3e6b18aa5d297edd8c66b1475c53b3f4b06f",
        "AI-WPS-P1-WORD-EXCEL-PPT-0.25.1-20260824-2e7a3e6b18aa5d297edd8c66b1475c53b3f4b06f",
        "ai-wps-phase1-delivery-20260824-2e7a3e6-v0251.tar.gz",
        "ai-wps-phase1-delivery-20260824-2e7a3e6-v0251.tar.gz.sha256",
        59,
    )
    generated = note.read_text(encoding="utf-8")
    for required in (
        "20260824-2e7a3e6",
        "AI-WPS-P1-WORD-EXCEL-PPT-0.25.1-20260824-2e7a3e6b18aa5d297edd8c66b1475c53b3f4b06f",
        "2e7a3e6b18aa5d297edd8c66b1475c53b3f4b06f",
        "ai-wps-phase1-delivery-20260824-2e7a3e6-v0251.tar.gz",
        "candidate",
        "manual-pending",
        "Issue #59",
    ):
        assert required in generated
    for stale in ("新候选待构建", "尚未构建", "修复中", "再形成新候选"):
        assert stale not in generated
    audit_module = load_v0251_audit_module()
    audit_module.audit_candidate_note(
        tmp_path,
        {
            "releaseDate": "20260824",
            "candidateEvidence": {
                "candidateBuildId": "AI-WPS-P1-WORD-EXCEL-PPT-0.25.1-20260824-2e7a3e6b18aa5d297edd8c66b1475c53b3f4b06f",
                "sourceCommit": "2e7a3e6b18aa5d297edd8c66b1475c53b3f4b06f",
                "archiveChecksumFile": "ai-wps-phase1-delivery-20260824-2e7a3e6-v0251.tar.gz.sha256",
            },
        },
    )


def test_v0251_audit_rejects_stale_delivery_note(tmp_path):
    audit_module = load_v0251_audit_module()
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "v0251-delivery.md").write_text(
        "v0.25.1-alpha 新候选待构建，当前修复中。", encoding="utf-8"
    )
    manifest = {
        "releaseDate": "20260824",
        "versionRule": "AI-WPS-P1-WORD-EXCEL-PPT-0.25.1-20260824",
        "candidateEvidence": {
            "candidateBuildId": "AI-WPS-P1-WORD-EXCEL-PPT-0.25.1-20260824-2e7a3e6b18aa5d297edd8c66b1475c53b3f4b06f",
            "sourceCommit": "2e7a3e6b18aa5d297edd8c66b1475c53b3f4b06f",
            "archiveChecksumFile": "ai-wps-phase1-delivery-20260824-2e7a3e6-v0251.tar.gz.sha256",
        },
        "targetAcceptanceIssue": 59,
        "targetAcceptance": {"status": "manual-pending"},
    }
    with pytest.raises(
        audit_module.DeliveryFailure,
        match="V0251_CANDIDATE_NOTE_STALE",
    ):
        audit_module.audit_candidate_note(tmp_path, manifest)
