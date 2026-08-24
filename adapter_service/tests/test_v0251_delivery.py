import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import tarfile
import shutil
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


def prepare_acceptance_sample(tmp_path, source_commit="1234567"):
    prepare_spec = importlib.util.spec_from_file_location(
        "v0251_prepare_sample", PREPARE
    )
    assert prepare_spec is not None and prepare_spec.loader is not None
    prepare_module = importlib.util.module_from_spec(prepare_spec)
    prepare_spec.loader.exec_module(prepare_module)
    archive = ROOT / (
        "dist-phase1-delivery-kit/"
        "ai-wps-phase1-delivery-20260824-10b251d-v0251.tar.gz"
    )
    baseline = ROOT / "dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260814-v0250.tar.gz"
    with tarfile.open(archive, "r:gz") as handle:
        handle.extractall(tmp_path)
    delivery = tmp_path / "ai-wps-phase1-delivery-20260824-10b251d-v0251"
    (delivery / "docs/v0251-target-machine-acceptance.md").write_text(
        (ROOT / "packaging/v0251-target-machine-acceptance.md").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    status_path = delivery / "docs/v0251-candidate-status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    frozen = next(
        record for record in status["records"] if record.get("archiveName") == archive.name
    )
    frozen["status"] = "rejected"
    frozen["archiveSha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
    status_path.write_text(json.dumps(status), encoding="utf-8")
    prepare_module.prepare(
        delivery,
        "20260824",
        baseline,
        archive,
        source_commit,
    )
    manifest = json.loads((delivery / "release-manifest.json").read_text(encoding="utf-8"))
    return delivery, manifest, archive


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
    assert record.count("<!-- V0251-CANDIDATE-CONTEXT:BEGIN -->") == 1
    assert record.count("<!-- V0251-CANDIDATE-CONTEXT:END -->") == 1
    assert "本记录是目标机现场填写模板" in record
    assert "当前源树没有活动候选" in record
    assert "10b251d" in record and "6949e76f929e092f6c4658a9498f9fd4a483260bee5d62d91e72b18009309120" in record
    assert "- 当前自动化候选：" not in record

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


def test_v0251_handoff_rejected_list_contains_previous_candidates_in_validation_context():
    handoff = (ROOT / "docs/codex-handoff.md").read_text(encoding="utf-8")

    validation = handoff.split("## 6. 验证状态", 1)[1].split("## 7. 目标机验证建议", 1)[0]
    rejected_candidates = _rejected_candidates_from_validation_section(validation)
    assert "20260824-ccad09f" in rejected_candidates
    assert "20260824-2e7a3e6" in rejected_candidates
    assert "20260824-5318d4b" in rejected_candidates
    assert "20260824-799adf9" in rejected_candidates
    assert "20260824-afe109c" in rejected_candidates
    assert "20260824-f953c58" in rejected_candidates
    assert "20260824-10b251d" in rejected_candidates
    assert "20260822-e43dc8c" in rejected_candidates

    candidate_only = (
        "`v0.25.1-alpha` 已将 `20260824-ccad09f` 登记为 `candidate`。"
    )
    assert _rejected_candidates_from_validation_section(candidate_only) == set()


def test_v0251_handoff_uses_superseded_candidate_as_previous_archive_example():
    handoff = (ROOT / "docs/codex-handoff.md").read_text(encoding="utf-8")

    assert (
        "AI_WPS_V0251_PREVIOUS_CANDIDATE_ARCHIVE="
        "dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260824-10b251d-v0251.tar.gz"
    ) in handoff
    assert "AI_WPS_V0251_PREVIOUS_CANDIDATE_ARCHIVE=dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260824-f953c58-v0251.tar.gz" not in handoff
    assert "AI_WPS_V0251_PREVIOUS_CANDIDATE_ARCHIVE=dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260822-e43dc8c-v0251.tar.gz" not in handoff


def test_v0251_candidate_identity_is_consistent_across_release_docs():
    status = json.loads(
        (ROOT / "packaging/v0251-candidate-status.json").read_text(encoding="utf-8")
    )
    expected_rejected = {
        "candidateBuildId": "AI-WPS-P1-WORD-EXCEL-PPT-0.25.1-20260824-10b251dd52ea6b6c2d60faa9cf0ab37b3ccdc2a5",
        "archiveName": "ai-wps-phase1-delivery-20260824-10b251d-v0251.tar.gz",
        "archiveChecksumFile": "ai-wps-phase1-delivery-20260824-10b251d-v0251.tar.gz.sha256",
        "sourceCommit": "10b251dd52ea6b6c2d60faa9cf0ab37b3ccdc2a5",
        "archiveSha256": "6949e76f929e092f6c4658a9498f9fd4a483260bee5d62d91e72b18009309120",
        "status": "rejected",
        "recordedAt": "20260824",
        "reason": "rejected: packaged target acceptance document contained contradictory current-candidate and no-current-candidate narratives plus duplicate previous rejected lines; archive is frozen and no active candidate remains until rebuilt",
    }
    assert status["records"][-2] == expected_rejected
    expected_current = {
        "candidateBuildId": "AI-WPS-P1-WORD-EXCEL-PPT-0.25.1-20260824-d7a1dd8ef4bd595c0e8611fdfffcf696eebe57f0",
        "archiveName": "ai-wps-phase1-delivery-20260824-d7a1dd8-v0251.tar.gz",
        "archiveChecksumFile": "ai-wps-phase1-delivery-20260824-d7a1dd8-v0251.tar.gz.sha256",
        "sourceCommit": "d7a1dd8ef4bd595c0e8611fdfffcf696eebe57f0",
        "archiveSha256": "ec318db4ffbda499c24aa6fb50958628cc4eaa030b22389bbf29cd783b1adbf6",
        "status": "candidate",
        "recordedAt": "20260824",
    }
    assert status["records"][-1] == expected_current
    assert [record for record in status["records"] if record.get("status") == "candidate"] == [expected_current]
    previous_current = next(
        record
        for record in status["records"]
        if record.get("candidateBuildId", "").endswith(
            "-799adf93cc1e594a82b6d2bc88abcf08b3f3c252"
        )
    )
    assert previous_current["archiveSha256"] == "5f15e385358dcaea987e62f43cd2db1b943696372a7867449a986cdfc403f67c"
    assert previous_current["status"] == "rejected"

    previous = next(
        record
        for record in status["records"]
        if record.get("candidateBuildId", "").endswith(
            "-5318d4b496d272a5f34bd270c714216f5b6c2e43"
        )
    )
    assert previous["archiveSha256"] == "2b5b48b7728c729016a97744af88d80a44fac63a2df7aa5eaf6ee32b50bf4320"
    assert previous["status"] == "rejected"

    rejected = next(
        record
        for record in status["records"]
        if record.get("candidateBuildId", "").endswith(
            "-2e7a3e6b18aa5d297edd8c66b1475c53b3f4b06f"
        )
    )
    assert rejected["archiveSha256"] == "576ad6580fc261e486adb3bac784d2e2a7f47c4f62209686bb1e2e58b5599c1e"
    assert rejected["status"] == "rejected"
    old_rejected = next(
        record
        for record in status["records"]
        if record.get("candidateBuildId", "").endswith(
            "-ccad09fb1d8019da3a40f14610ab3bd75de1ec23"
        )
    )
    assert old_rejected["archiveSha256"] == "2c3f8b5004c40fb7271a6afe7e4c8a292acb227b9d3ec08afc7f6b561d413a02"
    assert old_rejected["status"] == "rejected"

    identity = (
        "20260824-d7a1dd8",
        expected_current["candidateBuildId"],
        expected_current["sourceCommit"],
        expected_current["archiveName"],
        "ec318db4ffbda499c24aa6fb50958628cc4eaa030b22389bbf29cd783b1adbf6",
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

    readme_en = (ROOT / "README.md").read_text(encoding="utf-8")
    readme_zh = (ROOT / "README-ZH.md").read_text(encoding="utf-8")
    assert "direct predecessor `20260824-10b251d`" in readme_en
    assert "direct predecessor `20260824-afe109c`" in readme_en
    assert "其直接前任 `20260824-10b251d`" in readme_zh
    assert "`20260824-f953c58` 的直接前任 `20260824-afe109c`" in readme_zh

    validation_documents = documents[:2]
    for path in validation_documents:
        text = path.read_text(encoding="utf-8")
        delivery_lines = [
            line
            for line in text.splitlines()
            if (
                "delivery assertions" in line
                or "交付断言" in line
                or "delivery/prepare/audit focused" in line
                or "交付/prepare/audit focused" in line
            )
        ]
        aggregate_lines = [
            line
            for line in text.splitlines()
            if "Focused protocol/delivery aggregate" in line
            or "协议/交付 focused 合计" in line
        ]
        plugin_lines = [
            line
            for line in text.splitlines()
            if "Formal plugin contract tests" in line
            or "正式插件合同测试" in line
            or "正式插件契约" in line
        ]
        assert any("`87 passed`" in line for line in delivery_lines)
        assert all("`47 passed`" not in line for line in delivery_lines)
        assert all("`45 passed`" not in line for line in delivery_lines)
        assert all("`42 passed`" not in line for line in delivery_lines)
        assert any("`137 passed, 5 skipped`" in line for line in aggregate_lines)
        assert any("`28/28`" in line for line in plugin_lines)
        assert all("`25/25`" not in line for line in plugin_lines)

    assert "当前源码 Adapter 全量测试为 `874 passed, 95 skipped`" in (
        ROOT / "docs/codex-handoff.md"
    ).read_text(encoding="utf-8")
    assert "v0.25.1 交付/prepare/audit focused 为 `87 passed`" in (
        ROOT / "docs/codex-handoff.md"
    ).read_text(encoding="utf-8")

    candidate_archive = ROOT / (
        "dist-phase1-delivery-kit/"
        "ai-wps-phase1-delivery-20260824-d7a1dd8-v0251.tar.gz"
    )
    candidate_checksum = candidate_archive.with_name(candidate_archive.name + ".sha256")
    assert hashlib.sha256(candidate_archive.read_bytes()).hexdigest() == expected_current["archiveSha256"]
    assert candidate_checksum.read_text(encoding="utf-8").split() == [
        expected_current["archiveSha256"],
        candidate_archive.name,
    ]
    with tarfile.open(candidate_archive, "r:gz") as handle:
        packaged_acceptance = handle.extractfile(
            "ai-wps-phase1-delivery-20260824-d7a1dd8-v0251/docs/v0251-target-machine-acceptance.md"
        ).read().decode("utf-8")
    assert "- 当前自动化候选：`d7a1dd8`" in packaged_acceptance
    assert "candidateBuildId：`{0}`".format(expected_current["candidateBuildId"]) in packaged_acceptance
    source_template = (ROOT / "packaging/v0251-target-machine-acceptance.md").read_text(
        encoding="utf-8"
    )
    assert "当前源树没有活动候选" in source_template
    assert "- 当前自动化候选：" not in source_template

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


def test_v0251_prepare_accepts_frozen_previous_digest_and_rejects_mismatch(tmp_path):
    prepare_spec = importlib.util.spec_from_file_location("v0251_prepare", PREPARE)
    assert prepare_spec is not None and prepare_spec.loader is not None
    prepare_module = importlib.util.module_from_spec(prepare_spec)
    prepare_spec.loader.exec_module(prepare_module)

    archive = ROOT / "dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260824-10b251d-v0251.tar.gz"
    baseline = ROOT / "dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260814-v0250.tar.gz"
    with tarfile.open(archive, "r:gz") as handle:
        handle.extractall(tmp_path)
    delivery = tmp_path / "ai-wps-phase1-delivery-20260824-10b251d-v0251"
    (delivery / "docs/v0251-target-machine-acceptance.md").write_text(
        (ROOT / "packaging/v0251-target-machine-acceptance.md").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    status_path = delivery / "docs/v0251-candidate-status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    frozen = next(
        record
        for record in status["records"]
        if record.get("archiveName") == archive.name
    )
    frozen["status"] = "rejected"
    frozen["archiveSha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
    status_path.write_text(json.dumps(status), encoding="utf-8")

    prepare_module.prepare(delivery, "20260824", baseline, archive, "eb4c2b5")
    manifest = json.loads((delivery / "release-manifest.json").read_text(encoding="utf-8"))
    assert manifest["candidateEvidence"]["supersedes"]["status"] == "rejected"
    assert manifest["candidateEvidence"]["supersedes"]["archiveSha256"] == (
        "6949e76f929e092f6c4658a9498f9fd4a483260bee5d62d91e72b18009309120"
    )

    status = json.loads(status_path.read_text(encoding="utf-8"))
    frozen = next(
        record
        for record in status["records"]
        if record.get("archiveName") == archive.name
    )
    frozen["archiveSha256"] = "0" * 64
    status_path.write_text(json.dumps(status), encoding="utf-8")
    with pytest.raises(ValueError, match="V0251_PREVIOUS_CANDIDATE_STATUS_INVALID"):
        prepare_module.prepare(
            delivery,
            "20260824",
            baseline,
            archive,
            "ec4c2b5",
        )


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


@pytest.mark.parametrize("missing_row", (8, 9))
def test_v0251_audit_rejects_missing_mandatory_acceptance_row(tmp_path, missing_row):
    archive = ROOT / "dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260824-f953c58-v0251.tar.gz"
    with tarfile.open(archive, "r:gz") as handle:
        handle.extractall(tmp_path)
    delivery = tmp_path / "ai-wps-phase1-delivery-20260824-f953c58-v0251"
    record = delivery / "docs/v0251-target-machine-acceptance.md"
    content = record.read_text(encoding="utf-8")
    content = re.sub(r"^\| {0} \|.*\n".format(missing_row), "", content, flags=re.MULTILINE)
    record.write_text(content, encoding="utf-8")
    manifest = json.loads((delivery / "release-manifest.json").read_text(encoding="utf-8"))
    audit_module = load_v0251_audit_module()

    with pytest.raises(
        audit_module.DeliveryFailure,
        match="TARGET_ACCEPTANCE_RECORD_MANDATORY_ROWS_MISSING {0}".format(missing_row),
    ):
        audit_module.audit_target_acceptance_record(delivery, manifest)


def test_v0251_audit_rejects_duplicate_mandatory_acceptance_row(tmp_path):
    archive = ROOT / "dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260824-f953c58-v0251.tar.gz"
    with tarfile.open(archive, "r:gz") as handle:
        handle.extractall(tmp_path)
    delivery = tmp_path / "ai-wps-phase1-delivery-20260824-f953c58-v0251"
    record = delivery / "docs/v0251-target-machine-acceptance.md"
    content = record.read_text(encoding="utf-8")
    row = next(line for line in content.splitlines(True) if line.startswith("| 8 |"))
    record.write_text(content.replace(row, row + row, 1), encoding="utf-8")
    manifest = json.loads((delivery / "release-manifest.json").read_text(encoding="utf-8"))
    audit_module = load_v0251_audit_module()

    with pytest.raises(
        audit_module.DeliveryFailure,
        match="TARGET_ACCEPTANCE_RECORD_MANDATORY_ROWS_DUPLICATE 8",
    ):
        audit_module.audit_target_acceptance_record(delivery, manifest)


def test_v0251_audit_rejects_extra_mandatory_acceptance_row(tmp_path):
    archive = ROOT / "dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260824-f953c58-v0251.tar.gz"
    with tarfile.open(archive, "r:gz") as handle:
        handle.extractall(tmp_path)
    delivery = tmp_path / "ai-wps-phase1-delivery-20260824-f953c58-v0251"
    record = delivery / "docs/v0251-target-machine-acceptance.md"
    content = record.read_text(encoding="utf-8")
    marker = "### v2 后台格式审查判定矩阵"
    extra_row = "| 10 | Extra mandatory row | `manual-pending` | RED fixture |  |\n"
    record.write_text(content.replace(marker, extra_row + marker, 1), encoding="utf-8")
    manifest = json.loads((delivery / "release-manifest.json").read_text(encoding="utf-8"))
    audit_module = load_v0251_audit_module()

    with pytest.raises(
        audit_module.DeliveryFailure,
        match="TARGET_ACCEPTANCE_RECORD_MANDATORY_ROWS_EXTRA 10",
    ):
        audit_module.audit_target_acceptance_record(delivery, manifest)


def test_v0251_audit_rejects_packaged_acceptance_candidate_identity_mismatch(tmp_path):
    """The frozen 799adf9 package exposes the stale acceptance identity regression."""
    archive = ROOT / "dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260824-799adf9-v0251.tar.gz"
    with tarfile.open(archive, "r:gz") as handle:
        handle.extractall(tmp_path)
    delivery = tmp_path / "ai-wps-phase1-delivery-20260824-799adf9-v0251"
    manifest = json.loads((delivery / "release-manifest.json").read_text(encoding="utf-8"))
    audit_module = load_v0251_audit_module()

    with pytest.raises(
        audit_module.DeliveryFailure,
        match="V0251_TARGET_ACCEPTANCE_CANDIDATE_CONTEXT_DELIMITER_MISSING",
    ):
        audit_module.audit_target_acceptance_record(delivery, manifest)


def test_v0251_prepare_generated_tree_is_the_positive_acceptance_sample(tmp_path):
    """Only a freshly generated context block is a positive acceptance sample."""
    prepare_spec = importlib.util.spec_from_file_location("v0251_prepare_positive", PREPARE)
    assert prepare_spec is not None and prepare_spec.loader is not None
    prepare_module = importlib.util.module_from_spec(prepare_spec)
    prepare_spec.loader.exec_module(prepare_module)

    archive = ROOT / "dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260824-10b251d-v0251.tar.gz"
    baseline = ROOT / "dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260814-v0250.tar.gz"
    with tarfile.open(archive, "r:gz") as handle:
        handle.extractall(tmp_path)
    delivery = tmp_path / "ai-wps-phase1-delivery-20260824-10b251d-v0251"
    (delivery / "docs/v0251-target-machine-acceptance.md").write_text(
        (ROOT / "packaging/v0251-target-machine-acceptance.md").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    status_path = delivery / "docs/v0251-candidate-status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status["records"][-1]["status"] = "rejected"
    status["records"][-1]["archiveSha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
    status_path.write_text(json.dumps(status), encoding="utf-8")

    prepare_module.prepare(
        delivery,
        "20260824",
        baseline,
        archive,
        "1234567",
    )
    manifest = json.loads((delivery / "release-manifest.json").read_text(encoding="utf-8"))
    audit_module = load_v0251_audit_module()
    acceptance_content = (delivery / "docs/v0251-target-machine-acceptance.md").read_text(
        encoding="utf-8"
    )
    context = acceptance_content.split(
        "<!-- V0251-CANDIDATE-CONTEXT:BEGIN -->", 1
    )[1].split("<!-- V0251-CANDIDATE-CONTEXT:END -->", 1)[0]
    context_lines = [line.strip() for line in context.splitlines() if line.strip()]
    assert len(context_lines) == 3
    assert context_lines[0].startswith("- 当前自动化候选：")
    assert context_lines[1].startswith("- 上一被拒绝归档：")
    assert context_lines[2].startswith("- 候选状态：")
    assert manifest["candidateEvidence"]["supersedes"]["sourceCommit"].startswith(
        "10b251d"
    )
    assert "当前没有活动" not in context
    assert "修复源" not in context
    audit_module.audit_target_acceptance_record(delivery, manifest)


def test_v0251_prepare_rejects_noncanonical_source_basic_info_shell(tmp_path):
    prepare_spec = importlib.util.spec_from_file_location(
        "v0251_prepare_source_shell", PREPARE
    )
    assert prepare_spec is not None and prepare_spec.loader is not None
    prepare_module = importlib.util.module_from_spec(prepare_spec)
    prepare_spec.loader.exec_module(prepare_module)
    docs = tmp_path / "docs"
    docs.mkdir(parents=True)
    record = docs / "v0251-target-machine-acceptance.md"
    content = (ROOT / "packaging/v0251-target-machine-acceptance.md").read_text(
        encoding="utf-8"
    )
    record.write_text(
        content.replace(
            "## 基本信息\n",
            "## 基本信息\n- 源模板不允许出现额外基本信息行。\n",
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError, match="V0251_TARGET_ACCEPTANCE_BASIC_INFO_SCHEMA_MISMATCH"
    ):
        prepare_module.write_target_machine_acceptance_record(
            tmp_path,
            "1234567",
            "AI-WPS-P1-WORD-EXCEL-PPT-0.25.1-20260824-1234567",
            "ai-wps-phase1-delivery-20260824-1234567-v0251.tar.gz",
            "ai-wps-phase1-delivery-20260824-1234567-v0251.tar.gz.sha256",
            {
                "archiveName": "ai-wps-phase1-delivery-20260824-10b251d-v0251.tar.gz",
                "archiveSha256": "6" * 64,
                "candidateBuildId": "AI-WPS-P1-WORD-EXCEL-PPT-0.25.1-20260824-10b251d",
            },
            59,
        )


def test_v0251_frozen_10b_archive_is_rejected_by_candidate_context_audit(tmp_path):
    archive = ROOT / "dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260824-10b251d-v0251.tar.gz"
    with tarfile.open(archive, "r:gz") as handle:
        handle.extractall(tmp_path)
    delivery = tmp_path / "ai-wps-phase1-delivery-20260824-10b251d-v0251"
    manifest = json.loads((delivery / "release-manifest.json").read_text(encoding="utf-8"))
    audit_module = load_v0251_audit_module()

    with pytest.raises(
        audit_module.DeliveryFailure,
        match="V0251_TARGET_ACCEPTANCE_CANDIDATE_CONTEXT_DELIMITER_MISSING",
    ):
        audit_module.audit(delivery)


@pytest.mark.parametrize(
    "injection",
    (
        "- 当前没有活动的自动化候选；修复源在重新构建归档前不属于候选。",
        "- 新候选待构建；修复源尚未形成候选。",
        "- no active automated candidate; repair source is not a candidate.",
    ),
)
def test_v0251_audit_rejects_stale_candidate_context_narratives(tmp_path, injection):
    delivery, manifest, _archive = prepare_acceptance_sample(tmp_path)
    record = delivery / "docs/v0251-target-machine-acceptance.md"
    content = record.read_text(encoding="utf-8")
    marker = "<!-- V0251-CANDIDATE-CONTEXT:BEGIN -->"
    record.write_text(content.replace(marker, marker + "\n" + injection, 1), encoding="utf-8")
    audit_module = load_v0251_audit_module()

    with pytest.raises(
        audit_module.DeliveryFailure,
        match="V0251_TARGET_ACCEPTANCE_CANDIDATE_CONTEXT_STALE_NARRATIVE",
    ):
        audit_module.audit_target_acceptance_record(delivery, manifest)


@pytest.mark.parametrize(
    "injection,expected",
    (
        (
            "- 当前源树没有活动候选。",
            "V0251_TARGET_ACCEPTANCE_CANDIDATE_CONTEXT_STALE_NARRATIVE",
        ),
        (
            "- 额外候选上下文行不属于三行闭合语法。",
            "V0251_TARGET_ACCEPTANCE_CANDIDATE_CONTEXT_UNKNOWN_LINE",
        ),
    ),
)
def test_v0251_audit_rejects_candidate_context_extra_lines(tmp_path, injection, expected):
    delivery, manifest, _archive = prepare_acceptance_sample(tmp_path)
    record = delivery / "docs/v0251-target-machine-acceptance.md"
    content = record.read_text(encoding="utf-8")
    marker = "<!-- V0251-CANDIDATE-CONTEXT:BEGIN -->"
    record.write_text(
        content.replace(marker, marker + "\n" + injection, 1), encoding="utf-8"
    )
    audit_module = load_v0251_audit_module()

    with pytest.raises(audit_module.DeliveryFailure, match=expected):
        audit_module.audit_target_acceptance_record(delivery, manifest)


def test_v0251_audit_rejects_reordered_candidate_context_lines(tmp_path):
    delivery, manifest, _archive = prepare_acceptance_sample(tmp_path)
    record = delivery / "docs/v0251-target-machine-acceptance.md"
    content = record.read_text(encoding="utf-8")
    begin = "<!-- V0251-CANDIDATE-CONTEXT:BEGIN -->"
    end = "<!-- V0251-CANDIDATE-CONTEXT:END -->"
    context = content.split(begin, 1)[1].split(end, 1)[0]
    lines = [line for line in context.splitlines() if line.strip()]
    mutated = "\n".join((lines[2], lines[0], lines[1]))
    record.write_text(content.replace(begin + context + end, begin + "\n" + mutated + "\n" + end, 1), encoding="utf-8")
    audit_module = load_v0251_audit_module()

    with pytest.raises(
        audit_module.DeliveryFailure,
        match="V0251_TARGET_ACCEPTANCE_CANDIDATE_CONTEXT_ORDER_INVALID",
    ):
        audit_module.audit_target_acceptance_record(delivery, manifest)


def test_v0251_audit_rejects_candidate_context_outside_basic_information(tmp_path):
    delivery, manifest, _archive = prepare_acceptance_sample(tmp_path)
    record = delivery / "docs/v0251-target-machine-acceptance.md"
    content = record.read_text(encoding="utf-8")
    begin = "<!-- V0251-CANDIDATE-CONTEXT:BEGIN -->"
    end = "<!-- V0251-CANDIDATE-CONTEXT:END -->"
    context = content.split(begin, 1)[1].split(end, 1)[0]
    mutated = content.replace(
        begin + context + end,
        "## 候选附录\n" + begin + context + end,
        1,
    ).replace(
        "## 基本信息\n",
        "## 基本信息\n- 当前源树没有活动候选。\n",
        1,
    )
    record.write_text(mutated, encoding="utf-8")
    audit_module = load_v0251_audit_module()

    with pytest.raises(
        audit_module.DeliveryFailure,
        match="V0251_TARGET_ACCEPTANCE_CANDIDATE_CONTEXT_OUTSIDE_BASIC_INFO",
    ):
        audit_module.audit_target_acceptance_record(delivery, manifest)


def test_v0251_audit_rejects_basic_information_stale_text_outside_context(tmp_path):
    delivery, manifest, _archive = prepare_acceptance_sample(tmp_path)
    record = delivery / "docs/v0251-target-machine-acceptance.md"
    content = record.read_text(encoding="utf-8")
    record.write_text(
        content.replace(
            "## 基本信息\n",
            "## 基本信息\n- 当前源树没有活动候选。\n",
            1,
        ),
        encoding="utf-8",
    )
    audit_module = load_v0251_audit_module()

    with pytest.raises(
        audit_module.DeliveryFailure,
        match="V0251_TARGET_ACCEPTANCE_CANDIDATE_CONTEXT_STALE_NARRATIVE",
    ):
        audit_module.audit_target_acceptance_record(delivery, manifest)


@pytest.mark.parametrize("spaces", (1, 2, 3))
def test_v0251_audit_rejects_indented_next_heading_with_context_after_it(tmp_path, spaces):
    delivery, manifest, _archive = prepare_acceptance_sample(tmp_path)
    record = delivery / "docs/v0251-target-machine-acceptance.md"
    content = record.read_text(encoding="utf-8")
    begin = "<!-- V0251-CANDIDATE-CONTEXT:BEGIN -->"
    end = "<!-- V0251-CANDIDATE-CONTEXT:END -->"
    block = begin + content.split(begin, 1)[1].split(end, 1)[0] + end
    mutated = content.replace(block, "", 1).replace(
        "## 验收结论规则\n",
        " " * spaces + "## 验收结论规则\n" + block + "\n",
        1,
    )
    record.write_text(mutated, encoding="utf-8")
    audit_module = load_v0251_audit_module()

    with pytest.raises(
        audit_module.DeliveryFailure,
        match="V0251_TARGET_ACCEPTANCE_NEXT_HEADING_CARDINALITY_INVALID",
    ):
        audit_module.audit_target_acceptance_record(delivery, manifest)


def test_v0251_audit_rejects_fenced_fake_basic_information_heading(tmp_path):
    delivery, manifest, _archive = prepare_acceptance_sample(tmp_path)
    record = delivery / "docs/v0251-target-machine-acceptance.md"
    content = record.read_text(encoding="utf-8")
    begin = "<!-- V0251-CANDIDATE-CONTEXT:BEGIN -->"
    end = "<!-- V0251-CANDIDATE-CONTEXT:END -->"
    block = begin + content.split(begin, 1)[1].split(end, 1)[0] + end
    mutated = (
        "```markdown\n## 基本信息\n"
        + block
        + "\n```\n"
        + content.replace(block, "", 1)
    )
    record.write_text(mutated, encoding="utf-8")
    audit_module = load_v0251_audit_module()

    with pytest.raises(
        audit_module.DeliveryFailure,
        match="V0251_TARGET_ACCEPTANCE_BASIC_INFO_HEADING_CARDINALITY_INVALID",
    ):
        audit_module.audit_target_acceptance_record(delivery, manifest)


@pytest.mark.parametrize(
    "stale",
    (
        "当前不存在活动候选",
        "此源码仅供重新构建，不是候选",
        "no candidate is currently active",
    ),
)
def test_v0251_audit_rejects_stale_synonyms_outside_context(tmp_path, stale):
    delivery, manifest, _archive = prepare_acceptance_sample(tmp_path)
    record = delivery / "docs/v0251-target-machine-acceptance.md"
    content = record.read_text(encoding="utf-8")
    record.write_text(
        content.replace("## 基本信息\n", "## 基本信息\n- " + stale + "。\n", 1),
        encoding="utf-8",
    )
    audit_module = load_v0251_audit_module()

    with pytest.raises(
        audit_module.DeliveryFailure,
        match="V0251_TARGET_ACCEPTANCE_CANDIDATE_CONTEXT_STALE_NARRATIVE",
    ):
        audit_module.audit_target_acceptance_record(delivery, manifest)


@pytest.mark.parametrize(
    "prefix,suffix,expected",
    (
        (" ", "", "V0251_TARGET_ACCEPTANCE_CURRENT_CANDIDATE_LINE_MISSING"),
        ("    ", "", "V0251_TARGET_ACCEPTANCE_CURRENT_CANDIDATE_LINE_MISSING"),
        ("", " ", "V0251_TARGET_ACCEPTANCE_CANDIDATE_IDENTITY_MISMATCH"),
    ),
)
def test_v0251_audit_rejects_identity_whitespace_variants(
    tmp_path, prefix, suffix, expected
):
    delivery, manifest, _archive = prepare_acceptance_sample(tmp_path)
    record = delivery / "docs/v0251-target-machine-acceptance.md"
    content = record.read_text(encoding="utf-8")
    current = next(
        line for line in content.splitlines() if line.startswith("- 当前自动化候选：")
    )
    record.write_text(
        content.replace(current, prefix + current + suffix, 1), encoding="utf-8"
    )
    audit_module = load_v0251_audit_module()

    with pytest.raises(audit_module.DeliveryFailure, match=expected):
        audit_module.audit_target_acceptance_record(delivery, manifest)


def test_v0251_audit_rejects_arbitrary_extra_basic_information_line(tmp_path):
    delivery, manifest, _archive = prepare_acceptance_sample(tmp_path)
    record = delivery / "docs/v0251-target-machine-acceptance.md"
    content = record.read_text(encoding="utf-8")
    record.write_text(
        content.replace(
            "## 基本信息\n",
            "## 基本信息\n- 不属于封闭基本信息 schema 的额外行。\n",
            1,
        ),
        encoding="utf-8",
    )
    audit_module = load_v0251_audit_module()

    with pytest.raises(
        audit_module.DeliveryFailure,
        match="V0251_TARGET_ACCEPTANCE_BASIC_INFO_SCHEMA_MISMATCH",
    ):
        audit_module.audit_target_acceptance_record(delivery, manifest)


@pytest.mark.parametrize(
    "insertion,expected",
    (
        (
            "# v0.25.1 目标机整合验收记录\n",
            "V0251_TARGET_ACCEPTANCE_DOCUMENT_TITLE_CARDINALITY_INVALID",
        ),
        (
            "## 基本信息\n",
            "V0251_TARGET_ACCEPTANCE_BASIC_INFO_HEADING_CARDINALITY_INVALID",
        ),
        (
            "## 验收结论规则\n",
            "V0251_TARGET_ACCEPTANCE_NEXT_HEADING_CARDINALITY_INVALID",
        ),
    ),
)
def test_v0251_audit_rejects_duplicate_canonical_headings(tmp_path, insertion, expected):
    delivery, manifest, _archive = prepare_acceptance_sample(tmp_path)
    record = delivery / "docs/v0251-target-machine-acceptance.md"
    content = record.read_text(encoding="utf-8")
    record.write_text(
        content.replace(insertion, insertion + insertion, 1), encoding="utf-8"
    )
    audit_module = load_v0251_audit_module()

    with pytest.raises(audit_module.DeliveryFailure, match=expected):
        audit_module.audit_target_acceptance_record(delivery, manifest)


def test_v0251_audit_rejects_predecessor_deadbee_binding(tmp_path):
    delivery, manifest, _archive = prepare_acceptance_sample(tmp_path)
    evidence = manifest["candidateEvidence"]["supersedes"]
    old_build_id = evidence["candidateBuildId"]
    evidence["candidateBuildId"] = (
        "AI-WPS-P1-WORD-EXCEL-PPT-0.25.1-20260824-deadbee"
    )
    record = delivery / "docs/v0251-target-machine-acceptance.md"
    content = record.read_text(encoding="utf-8")
    record.write_text(content.replace(old_build_id, evidence["candidateBuildId"], 1), encoding="utf-8")
    audit_module = load_v0251_audit_module()

    with pytest.raises(
        audit_module.DeliveryFailure,
        match="V0251_SUPERSEDED_CANDIDATE_SOURCE_BINDING_INVALID",
    ):
        audit_module.audit_candidate_lineage(delivery, manifest)


def test_v0251_audit_rejects_predecessor_build_id_archive_short_mismatch(tmp_path):
    delivery, manifest, _archive = prepare_acceptance_sample(tmp_path)
    evidence = manifest["candidateEvidence"]["supersedes"]
    old_build_id = evidence["candidateBuildId"]
    mismatched_source = "deadbeef" * 5
    evidence["candidateBuildId"] = (
        "AI-WPS-P1-WORD-EXCEL-PPT-0.25.1-20260824-" + mismatched_source
    )
    evidence["sourceCommit"] = mismatched_source
    record = delivery / "docs/v0251-target-machine-acceptance.md"
    content = record.read_text(encoding="utf-8")
    record.write_text(content.replace(old_build_id, evidence["candidateBuildId"], 1), encoding="utf-8")
    audit_module = load_v0251_audit_module()

    with pytest.raises(
        audit_module.DeliveryFailure,
        match="V0251_SUPERSEDED_CANDIDATE_SOURCE_BINDING_INVALID",
    ):
        audit_module.audit_candidate_lineage(delivery, manifest)


def test_v0251_prepare_rejects_previous_archive_source_binding_mismatch(tmp_path):
    prepare_spec = importlib.util.spec_from_file_location(
        "v0251_prepare_binding", PREPARE
    )
    assert prepare_spec is not None and prepare_spec.loader is not None
    prepare_module = importlib.util.module_from_spec(prepare_spec)
    prepare_spec.loader.exec_module(prepare_module)
    frozen = ROOT / "dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260824-10b251d-v0251.tar.gz"
    mismatched = tmp_path / "ai-wps-phase1-delivery-20260824-deadbee-v0251.tar.gz"
    shutil.copyfile(frozen, mismatched)

    with pytest.raises(
        ValueError,
        match="V0251_PREVIOUS_CANDIDATE_SOURCE_BINDING_INVALID",
    ):
        prepare_module.previous_candidate_metadata(mismatched)


@pytest.mark.parametrize(
    "mutation,expected",
    (
        (
            lambda context, current, previous, state: context.replace(
                previous, previous + "\n" + previous, 1
            ),
            "V0251_TARGET_ACCEPTANCE_SUPERSEDED_LINE_DUPLICATE",
        ),
        (
            lambda context, current, previous, state: context.replace(
                "10b251d-v0251.tar.gz", "799adf9-v0251.tar.gz", 1
            ),
            "V0251_TARGET_ACCEPTANCE_SUPERSEDED_IDENTITY_MISMATCH",
        ),
        (
            lambda context, current, previous, state: context.replace(
                current, current + "\n" + current, 1
            ),
            "V0251_TARGET_ACCEPTANCE_CURRENT_CANDIDATE_LINE_DUPLICATE",
        ),
        (
            lambda context, current, previous, state: context.replace(
                "1234567", "7654321", 1
            ),
            "V0251_TARGET_ACCEPTANCE_CANDIDATE_IDENTITY_MISMATCH",
        ),
    ),
)
def test_v0251_audit_rejects_candidate_context_identity_cardinality(
    tmp_path, mutation, expected
):
    delivery, manifest, _archive = prepare_acceptance_sample(tmp_path)
    record = delivery / "docs/v0251-target-machine-acceptance.md"
    content = record.read_text(encoding="utf-8")
    begin = "<!-- V0251-CANDIDATE-CONTEXT:BEGIN -->"
    end = "<!-- V0251-CANDIDATE-CONTEXT:END -->"
    context = content.split(begin, 1)[1].split(end, 1)[0]
    lines = [line for line in context.splitlines() if line.strip()]
    current = next(line for line in lines if line.startswith("- 当前自动化候选："))
    previous = next(line for line in lines if line.startswith("- 上一被拒绝归档："))
    state = next(line for line in lines if line.startswith("- 候选状态："))
    mutated = mutation(context, current, previous, state)
    record.write_text(
        content.replace(begin + context + end, begin + mutated + end, 1),
        encoding="utf-8",
    )
    audit_module = load_v0251_audit_module()

    with pytest.raises(audit_module.DeliveryFailure, match=expected):
        audit_module.audit_target_acceptance_record(delivery, manifest)


@pytest.mark.parametrize(
    "which,operation,expected",
    (
        ("begin", "remove", "V0251_TARGET_ACCEPTANCE_CANDIDATE_CONTEXT_DELIMITER_MISSING"),
        ("end", "remove", "V0251_TARGET_ACCEPTANCE_CANDIDATE_CONTEXT_DELIMITER_MISSING"),
        ("begin", "duplicate", "V0251_TARGET_ACCEPTANCE_CANDIDATE_CONTEXT_DELIMITER_DUPLICATE"),
        ("end", "duplicate", "V0251_TARGET_ACCEPTANCE_CANDIDATE_CONTEXT_DELIMITER_DUPLICATE"),
    ),
)
def test_v0251_audit_rejects_candidate_context_delimiter_cardinality(
    tmp_path, which, operation, expected
):
    delivery, manifest, _archive = prepare_acceptance_sample(tmp_path)
    record = delivery / "docs/v0251-target-machine-acceptance.md"
    content = record.read_text(encoding="utf-8")
    marker = (
        "<!-- V0251-CANDIDATE-CONTEXT:{0} -->".format(which.upper())
    )
    replacement = "" if operation == "remove" else marker + "\n" + marker
    record.write_text(content.replace(marker, replacement, 1), encoding="utf-8")
    audit_module = load_v0251_audit_module()

    with pytest.raises(audit_module.DeliveryFailure, match=expected):
        audit_module.audit_target_acceptance_record(delivery, manifest)


@pytest.mark.parametrize(
    "operation,expected",
    (
        ("remove", "V0251_TARGET_ACCEPTANCE_CANDIDATE_STATE_MISSING"),
        ("duplicate", "V0251_TARGET_ACCEPTANCE_CANDIDATE_STATE_DUPLICATE"),
    ),
)
def test_v0251_audit_rejects_candidate_state_cardinality(tmp_path, operation, expected):
    delivery, manifest, _archive = prepare_acceptance_sample(tmp_path)
    record = delivery / "docs/v0251-target-machine-acceptance.md"
    content = record.read_text(encoding="utf-8")
    begin = "<!-- V0251-CANDIDATE-CONTEXT:BEGIN -->"
    end = "<!-- V0251-CANDIDATE-CONTEXT:END -->"
    context = content.split(begin, 1)[1].split(end, 1)[0]
    state = next(line for line in context.splitlines() if line.startswith("- 候选状态："))
    if operation == "remove":
        mutated = context.replace(state + "\n", "", 1)
    else:
        mutated = context.replace(state, state + "\n" + state, 1)
    record.write_text(
        content.replace(begin + context + end, begin + mutated + end, 1),
        encoding="utf-8",
    )
    audit_module = load_v0251_audit_module()

    with pytest.raises(audit_module.DeliveryFailure, match=expected):
        audit_module.audit_target_acceptance_record(delivery, manifest)


def test_v0251_audit_rejects_second_status_candidate(tmp_path):
    delivery, manifest, _archive = prepare_acceptance_sample(tmp_path)
    status_path = delivery / "docs/v0251-candidate-status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    current = next(record for record in status["records"] if record.get("status") == "candidate")
    duplicate = dict(current)
    duplicate["candidateBuildId"] = duplicate["candidateBuildId"].replace("1234567", "7654321")
    status["records"].append(duplicate)
    status_path.write_text(json.dumps(status), encoding="utf-8")
    audit_module = load_v0251_audit_module()

    with pytest.raises(
        audit_module.DeliveryFailure,
        match="V0251_TARGET_ACCEPTANCE_STATUS_CANDIDATE_CARDINALITY_INVALID",
    ):
        audit_module.audit_target_acceptance_record(delivery, manifest)


def test_v0251_audit_rejects_missing_packaged_acceptance_document(tmp_path):
    audit_module = load_v0251_audit_module()

    with pytest.raises(
        audit_module.DeliveryFailure,
        match="TARGET_ACCEPTANCE_RECORD_MISSING",
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


@pytest.mark.parametrize(
    "archive_name,expected_digest",
    (
        (
            "ai-wps-phase1-delivery-20260824-f953c58-v0251.tar.gz",
            "833e71fcf5a6e2172c93e44cc3502d46e1ea89c5dc4abb77f658ac8c5ee77ee7",
        ),
        (
            "ai-wps-phase1-delivery-20260824-10b251d-v0251.tar.gz",
            "6949e76f929e092f6c4658a9498f9fd4a483260bee5d62d91e72b18009309120",
        ),
    ),
)
def test_v0251_frozen_archive_checksums_remain_exact(archive_name, expected_digest):
    archive = ROOT / "dist-phase1-delivery-kit" / archive_name
    checksum = archive.with_name(archive.name + ".sha256")
    assert archive.is_file()
    assert checksum.is_file()
    audit_module = load_v0251_audit_module()
    audit_module.audit_archive_checksum(archive, checksum, archive.name)
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == expected_digest
    assert checksum.read_text(encoding="utf-8").split() == [expected_digest, archive.name]


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
    (delivery / "docs/v0251-target-machine-acceptance.md").write_text(
        (ROOT / "packaging/v0251-target-machine-acceptance.md").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
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
    acceptance = (delivery / "docs/v0251-target-machine-acceptance.md").read_text(
        encoding="utf-8"
    )
    assert (
        "- 当前自动化候选：`b7a1cf9`，状态为 `candidate`；"
        "candidateBuildId：`AI-WPS-P1-WORD-EXCEL-PPT-0.25.1-20260822-b7a1cf9`；"
        "源码提交：`b7a1cf9`；归档：`ai-wps-phase1-delivery-20260822-b7a1cf9-v0251.tar.gz`；"
        "校验文件：`ai-wps-phase1-delivery-20260822-b7a1cf9-v0251.tar.gz.sha256`；"
        "目标验收：`manual-pending`（Issue #59）"
    ) in acceptance
    assert "`OutlineLevel=0`" in acceptance
    assert "`OutlineLevel=10`" in acceptance
    assert "`OutlineLevel=1..9`" in acceptance
    assert "`表格/嵌套表格`" in acceptance
    assert "`图片元数据`" in acceptance
    assert "`非 BMP emoji`" in acceptance
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
        "5318d4b496d272a5f34bd270c714216f5b6c2e43",
        "AI-WPS-P1-WORD-EXCEL-PPT-0.25.1-20260824-5318d4b496d272a5f34bd270c714216f5b6c2e43",
        "ai-wps-phase1-delivery-20260824-5318d4b-v0251.tar.gz",
        "ai-wps-phase1-delivery-20260824-5318d4b-v0251.tar.gz.sha256",
        59,
    )
    generated = note.read_text(encoding="utf-8")
    for required in (
        "20260824-5318d4b",
        "AI-WPS-P1-WORD-EXCEL-PPT-0.25.1-20260824-5318d4b496d272a5f34bd270c714216f5b6c2e43",
        "5318d4b496d272a5f34bd270c714216f5b6c2e43",
        "ai-wps-phase1-delivery-20260824-5318d4b-v0251.tar.gz",
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
                "candidateBuildId": "AI-WPS-P1-WORD-EXCEL-PPT-0.25.1-20260824-5318d4b496d272a5f34bd270c714216f5b6c2e43",
                "sourceCommit": "5318d4b496d272a5f34bd270c714216f5b6c2e43",
                "archiveChecksumFile": "ai-wps-phase1-delivery-20260824-5318d4b-v0251.tar.gz.sha256",
            },
        },
    )


@pytest.mark.parametrize(
    "stale_text",
    (
        "新候选待构建",
        "新候选尚未形成",
        "候选尚未形成",
        "新候选尚未生成",
        "候选尚未生成",
        "新候选尚未构建",
        "候选尚未构建",
        "candidate has not yet been formed",
        "candidate has not yet been created",
        "candidate has not yet been generated",
        "candidate has not yet been built",
        "candidate not yet built",
        "candidate not yet created",
        "candidate not yet formed",
        "candidate not yet generated",
    ),
)
def test_v0251_audit_rejects_stale_delivery_note(tmp_path, stale_text):
    audit_module = load_v0251_audit_module()
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "v0251-delivery.md").write_text(
        "v0.25.1-alpha {0}，记录待验证。".format(stale_text), encoding="utf-8"
    )
    manifest = {
        "releaseDate": "20260824",
        "versionRule": "AI-WPS-P1-WORD-EXCEL-PPT-0.25.1-20260824",
        "candidateEvidence": {
            "candidateBuildId": "AI-WPS-P1-WORD-EXCEL-PPT-0.25.1-20260824-5318d4b496d272a5f34bd270c714216f5b6c2e43",
            "sourceCommit": "5318d4b496d272a5f34bd270c714216f5b6c2e43",
            "archiveChecksumFile": "ai-wps-phase1-delivery-20260824-5318d4b-v0251.tar.gz.sha256",
        },
        "targetAcceptanceIssue": 59,
        "targetAcceptance": {"status": "manual-pending"},
    }
    with pytest.raises(
        audit_module.DeliveryFailure,
        match="V0251_CANDIDATE_NOTE_STALE",
    ):
        audit_module.audit_candidate_note(tmp_path, manifest)
