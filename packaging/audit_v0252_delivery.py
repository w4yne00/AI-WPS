#!/usr/bin/env python3
"""Audit the assembled v0.25.2-alpha Phase1 candidate."""

import argparse
from datetime import datetime
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set


VERSION = "0.25.2-alpha"
BASELINE_VERSION = "0.25.1-alpha"
FORMAT_ASSET_VERSION = "0.25.1-format-rules-alpha"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{7,40}$")
BUILD_ID_RE = re.compile(
    r"^AI-WPS-P1-WORD-EXCEL-PPT-0\.25\.2-[0-9]{8}-[0-9a-f]{7,40}$"
)
PREVIOUS_BUILD_ID_RE = re.compile(
    r"^AI-WPS-P1-WORD-EXCEL-PPT-0\.25\.[12]-[0-9]{8}(?:-[0-9a-f]{7,40})?$"
)
REFERENCE_WORKFLOWS = {
    "reference-workflows/format-semantics-text-v1.yml",
    "reference-workflows/format-semantics-vision-v1.yml",
}
FORBIDDEN_SCOPE_PARTS = {"material_composer", "adr-0116", "d-0001", "adr-0117"}
TARGET_ACCEPTANCE_MATRIX_MARKERS = (
    "`OutlineLevel=0`",
    "`OutlineLevel=10`",
    "`OutlineLevel=1..9`",
    "`表格/嵌套表格`",
    "`图片元数据`",
    "`非 BMP emoji`",
    "`dataStatus=insufficient`",
    "其它 `dataStatus`",
)
CANDIDATE_CONTEXT_BEGIN = "<!-- V0252-CANDIDATE-CONTEXT:BEGIN -->"
CANDIDATE_CONTEXT_END = "<!-- V0252-CANDIDATE-CONTEXT:END -->"
CANONICAL_DOCUMENT_TITLE = "# v0.25.2 目标机整合验收记录"
CANONICAL_BASIC_INFO_HEADING = "## 基本信息"
CANONICAL_NEXT_HEADING = "## 验收结论规则"
CANONICAL_BASIC_INFO_STATIC_LINES = (
    "- 对应工单：[Issue #59](https://github.com/w4yne00/AI-WPS/issues/59)",
    "- 验收版本：`v0.25.2-alpha`",
    "- 验收范围：麒麟 V10 ARM、目标 WPS、`cloud` 用户环境",
    "- 当前记录状态：`manual-pending`",
)
CANONICAL_OPERATOR_LINES = (
    "- 验收人员：",
    "- 验收日期：",
    "- 交付包文件名：",
    "- 交付包 SHA-256：",
    "- v0.25.1 基线包 SHA-256：",
)
CANONICAL_BASIC_INFO_INTRO = (
    "本记录是目标机现场填写模板。候选上下文由 `prepare_v0252_delivery.py` 在组装交付树时整体生成；"
    "自动化门禁只能证明候选构建，不能替代麒麟 V10、目标 WPS 和 `cloud` 用户环境中的真实操作。"
    "所有现场原始命令输出、截图、目标机编号、账号信息、配置内容、API Key、文档正文和模型原始回复"
    "只保留在受控验收记录中，不写入仓库。"
)
CANONICAL_SOURCE_CONTEXT_LINE = (
    "- 当前源树没有活动的 0.25.2 候选；冻结的 `v0.25.1-alpha` 候选 `d7a1dd8` 保持原字节，"
    "SHA-256 为 `ec318db4ffbda499c24aa6fb50958628cc4eaa030b22389bbf29cd783b1adbf6`，"
    "状态仍为 `candidate`，不是 0.25.2 当前候选。"
)
CANDIDATE_CONTEXT_STALE_PATTERNS = (
    re.compile(r"当前源树没有活动候选"),
    re.compile(r"当前不存在活动候选"),
    re.compile(r"此源码仅供重新构建，不是候选"),
    re.compile(r"当前没有(?:(?:活动)(?:的)?|自动化)?候选"),
    re.compile(r"修复源.*(?:不属于|尚未).*(?:候选|candidate)", re.IGNORECASE),
    re.compile(r"(?:新候选|候选).*(?:待构建|尚未构建|未形成|未生成|重建前)"),
    re.compile(r"(?:重建|重新构建).*(?:前|后才|才能).*(?:候选|通过)"),
    re.compile(r"\brebuild[- ]only\b", re.IGNORECASE),
    re.compile(r"\bno\s+(?:current|active)\s+(?:automated\s+)?candidate\b", re.IGNORECASE),
    re.compile(r"\bno\s+candidate\s+is\s+currently\s+active\b", re.IGNORECASE),
    re.compile(r"\b(?:current\s+candidate|candidate)\s+does\s+not\s+exist\b", re.IGNORECASE),
    re.compile(r"\brepair\s+source\s+is\s+not\s+(?:a\s+)?candidate\b", re.IGNORECASE),
    re.compile(r"\bnew\s+candidate.*(?:pending\s+build|build\s+later)\b", re.IGNORECASE),
)


def _non_empty_lines(content: str) -> List[str]:
    """Return raw non-empty lines; content lines are never normalized."""
    return [line for line in content.splitlines() if line and not line.isspace()]


def _basic_information_bounds(content: str) -> tuple:
    """Return character bounds for diagnostics before the closed schema check."""
    lines = content.splitlines(keepends=True)
    basic_index = next(
        (index for index, line in enumerate(lines) if line.rstrip("\r\n") == CANONICAL_BASIC_INFO_HEADING),
        None,
    )
    if basic_index is None:
        raise DeliveryFailure("V0252_TARGET_ACCEPTANCE_BASIC_INFO_SECTION_MISSING")
    next_index = next(
        (
            index
            for index in range(basic_index + 1, len(lines))
            if lines[index].rstrip("\r\n").startswith("## ")
            and not lines[index].rstrip("\r\n").startswith("### ")
        ),
        len(lines),
    )
    start = sum(len(line) for line in lines[:basic_index])
    end = sum(len(line) for line in lines[:next_index])
    return start, end


def _basic_info_schema_lines(context_lines: List[str]) -> List[str]:
    return [
        CANONICAL_DOCUMENT_TITLE,
        CANONICAL_BASIC_INFO_HEADING,
        *CANONICAL_BASIC_INFO_STATIC_LINES,
        CANDIDATE_CONTEXT_BEGIN,
        *context_lines,
        CANDIDATE_CONTEXT_END,
        *CANONICAL_OPERATOR_LINES,
        CANONICAL_BASIC_INFO_INTRO,
        CANONICAL_NEXT_HEADING,
    ]


def _validate_basic_info_schema(content: str, context_lines: List[str]) -> None:
    """Require the complete packaged basic-info prefix as raw non-empty lines."""
    lines = _non_empty_lines(content)
    expected = _basic_info_schema_lines(context_lines)
    if lines.count(CANONICAL_DOCUMENT_TITLE) != 1:
        raise DeliveryFailure("V0252_TARGET_ACCEPTANCE_DOCUMENT_TITLE_CARDINALITY_INVALID")
    if lines.count(CANONICAL_BASIC_INFO_HEADING) != 1:
        raise DeliveryFailure("V0252_TARGET_ACCEPTANCE_BASIC_INFO_HEADING_CARDINALITY_INVALID")
    if lines.count(CANONICAL_NEXT_HEADING) != 1:
        raise DeliveryFailure("V0252_TARGET_ACCEPTANCE_NEXT_HEADING_CARDINALITY_INVALID")
    if lines.count(CANDIDATE_CONTEXT_BEGIN) != 1 or lines.count(CANDIDATE_CONTEXT_END) != 1:
        raise DeliveryFailure("V0252_TARGET_ACCEPTANCE_CANDIDATE_CONTEXT_DELIMITER_INVALID")
    if len(lines) < len(expected) or lines[: len(expected)] != expected:
        raise DeliveryFailure("V0252_TARGET_ACCEPTANCE_BASIC_INFO_SCHEMA_MISMATCH")


def _archive_source_binding(
    archive_name: str,
    source_commit: object,
    candidate_build_id: object,
    error_code: str,
) -> None:
    """Bind a source-bearing archive name to its manifest source/build suffix."""
    match = re.fullmatch(
        r"ai-wps-phase1-delivery-(?P<date>[0-9]{8})"
        r"(?:-(?P<source>[0-9a-f]{7}))?-v025(?P<series>[12])\.tar\.gz",
        str(archive_name),
    )
    if match is None or match.group("source") is None:
        # Legacy archives without a source segment predate the binding contract.
        return
    source = str(source_commit)
    build_id = str(candidate_build_id)
    if (
        not COMMIT_RE.fullmatch(source)
        or not PREVIOUS_BUILD_ID_RE.fullmatch(build_id)
        or not build_id.endswith("-" + source)
        or not source.startswith(match.group("source"))
        or not build_id.startswith(
            "AI-WPS-P1-WORD-EXCEL-PPT-0.25.{0}-{1}-".format(match.group("series"), match.group("date"))
        )
    ):
        raise DeliveryFailure(error_code)


class DeliveryFailure(RuntimeError):
    pass


LEGACY_FORMAT_MARKERS = (
    "general-office",
    "technical-file-format-requirements",
    "technical-file-structure-rules",
    "templates/company/technical-file-",
)
AUDIT_SCRIPT_NAMES = {
    "audit_format_rule_assets.py",
    "audit_v0250_delivery.py",
    "audit_v0251_delivery.py",
    "audit_v0252_delivery.py",
}
STALE_CANDIDATE_NOTE_PATTERNS = (
    re.compile(r"新?候选(?:待构建|尚未(?:形成|生成|构建)|未(?:形成|生成|构建))"),
    re.compile(r"尚未构建"),
    re.compile(r"修复中"),
    re.compile(r"再形成新候选"),
    re.compile(
        r"\b(?:new\s+)?candidate\s+(?:has\s+)?not\s+yet\s+"
        r"(?:been\s+)?(?:formed|created|generated|built)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:new\s+)?candidate\s+not\s+yet\s+"
        r"(?:formed|created|generated|built)\b",
        re.IGNORECASE,
    ),
    re.compile(r"new candidate archive remains pending build", re.IGNORECASE),
    re.compile(r"repair is in progress", re.IGNORECASE),
    re.compile(r"build a new candidate later", re.IGNORECASE),
)


def load_json(path: Path, code: str) -> Dict:
    if not path.is_file():
        raise DeliveryFailure(code)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DeliveryFailure(code)
    return value


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit_no_legacy_format_references(root: Path) -> None:
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".css", ".html", ".js", ".json", ".md", ".py", ".sh", ".txt", ".xml", ".yml"}:
            continue
        if path.name in AUDIT_SCRIPT_NAMES and path.parent.name == "scripts":
            continue
        content = path.read_text(encoding="utf-8")
        if any(marker in content for marker in LEGACY_FORMAT_MARKERS):
            raise DeliveryFailure("LEGACY_FORMAT_REFERENCE {0}".format(path.relative_to(root)))
        if path.relative_to(root).as_posix().startswith("packages/adapter-start-kit/templates/"):
            raise DeliveryFailure("HISTORICAL_TEMPLATE_ASSET_DELIVERED")


def audit_archive_checksum(
    archive: Path, checksum_file: Path, expected_archive_name: Optional[str] = None
) -> None:
    if not archive.is_file() or not checksum_file.is_file():
        raise DeliveryFailure("V0252_ARCHIVE_CHECKSUM_FILE_MISSING")
    fields = checksum_file.read_text(encoding="utf-8").strip().split()
    if len(fields) != 2 or not SHA256_RE.fullmatch(fields[0]):
        raise DeliveryFailure("V0252_ARCHIVE_CHECKSUM_FORMAT_INVALID")
    if fields[1] != (expected_archive_name or archive.name):
        raise DeliveryFailure("V0252_ARCHIVE_CHECKSUM_NAME_MISMATCH")
    if fields[0] != sha256(archive):
        raise DeliveryFailure("V0252_ARCHIVE_CHECKSUM_MISMATCH")


def safe_path(root: Path, value: str, code: str) -> Path:
    path = Path(value)
    if not value or path.is_absolute() or ".." in path.parts or "\\" in value:
        raise DeliveryFailure("{0} {1}".format(code, value))
    target = root / path
    if not target.is_file():
        raise DeliveryFailure("{0} {1}".format(code, value))
    return target


def audit_format_assets(root: Path, manifest: Dict) -> None:
    assets = load_json(root / "format-rule-assets-manifest.json", "FORMAT_ASSETS_MANIFEST_MISSING")
    if assets.get("version") != FORMAT_ASSET_VERSION or assets.get("deliveryVersion") != VERSION:
        raise DeliveryFailure("FORMAT_ASSETS_VERSION_INVALID")
    rule_pack_path = safe_path(root, assets.get("rulePack", ""), "FORMAT_RULE_PACK_REFERENCE_INVALID")
    notice_path = safe_path(root, assets.get("algorithm", {}).get("notice", ""), "THIRD_PARTY_NOTICE_REFERENCE_INVALID")
    gate_path = safe_path(root, assets.get("python", {}).get("compatibilityGate", ""), "PYTHON38_GATE_REFERENCE_INVALID")
    if "THIRD_PARTY_NOTICES" not in notice_path.name or not gate_path.name.endswith("check_python38_compatibility.py"):
        raise DeliveryFailure("FORMAT_ASSETS_REFERENCE_INVALID")
    rule_pack = load_json(rule_pack_path, "FORMAT_RULE_PACK_MISSING")
    algorithm = rule_pack.get("algorithm", {})
    if algorithm.get("writeBack") is not False or "defaultTemplateValues" in algorithm:
        raise DeliveryFailure("FORMAT_RULE_PACK_WRITEBACK_OR_DEFAULTS_ENABLED")
    algorithm_path = safe_path(root, algorithm.get("adapterPath", ""), "FORMAT_ALGORITHM_REFERENCE_INVALID")
    source_template_path = algorithm_path.parent / "assets/wx_template.docx"
    if not source_template_path.is_file():
        raise DeliveryFailure("FORMAT_TEMPLATE_SOURCE_MISSING")
    source_manifest_path = safe_path(root, algorithm.get("sourceManifest", ""), "FORMAT_SOURCE_MANIFEST_REFERENCE_INVALID")
    source_classification_path = safe_path(
        root, algorithm.get("sourceClassification", ""), "FORMAT_SOURCE_CLASSIFICATION_REFERENCE_INVALID"
    )
    if not SHA256_RE.fullmatch(str(algorithm.get("adapterSha256", ""))) or sha256(algorithm_path) != algorithm["adapterSha256"]:
        raise DeliveryFailure("FORMAT_ALGORITHM_HASH_MISMATCH")
    if not SHA256_RE.fullmatch(str(algorithm.get("sourceManifestSha256", ""))) or sha256(source_manifest_path) != algorithm["sourceManifestSha256"]:
        raise DeliveryFailure("FORMAT_SOURCE_MANIFEST_HASH_MISMATCH")
    if not SHA256_RE.fullmatch(str(algorithm.get("sourceClassificationSha256", ""))) or sha256(source_classification_path) != algorithm["sourceClassificationSha256"]:
        raise DeliveryFailure("FORMAT_SOURCE_CLASSIFICATION_HASH_MISMATCH")
    if sha256(source_template_path) != rule_pack.get("template", {}).get("sourceDocumentSha256"):
        raise DeliveryFailure("FORMAT_TEMPLATE_SOURCE_HASH_MISMATCH")
    references = manifest.get("formatReview", {}).get("referenceWorkflows", [])
    if set(references) != REFERENCE_WORKFLOWS:
        raise DeliveryFailure("FORMAT_REFERENCE_WORKFLOW_SET_INVALID")
    for relative in sorted(REFERENCE_WORKFLOWS):
        workflow = safe_path(root, relative, "FORMAT_REFERENCE_WORKFLOW_MISSING")
        content = workflow.read_text(encoding="utf-8")
        if "contract_version: format_semantics.v1" not in content or "variable: result_json" not in content:
            raise DeliveryFailure("FORMAT_REFERENCE_WORKFLOW_CONTRACT_INVALID")
        if any(token in content.lower() for token in ("api_key", "apikey", "providerbaseurl", "servicebaseurl", "http://", "https://")):
            raise DeliveryFailure("FORMAT_REFERENCE_WORKFLOW_SECRET_OR_ADDRESS")
        expected = (
            "ffe15d87ff293b82c39b5865f9299f9c857a8662738ef8e9e6b4ec31f4bca1c3"
            if relative.endswith("text-v1.yml")
            else "ac2324e4620e4d945046745ac660393a9a51827796c902cc65ebc3ab49d52ec4"
        )
        if sha256(workflow) != expected:
            raise DeliveryFailure("FORMAT_REFERENCE_WORKFLOW_HASH_MISMATCH")


def audit_visual_default(root: Path, manifest: Dict) -> None:
    visual = manifest.get("visualPolicy", {})
    if visual.get("enabledByDefault") is not True:
        raise DeliveryFailure("VISUAL_DEFAULT_MUST_BE_OPEN")
    if visual.get("requiresWpsAcceptance") is not False:
        raise DeliveryFailure("VISUAL_MUST_NOT_REQUIRE_WPS_ACCEPTANCE")
    for key in ("pixelExportWhenDisabled", "pixelUploadWhenDisabled", "imageSlotAllocationWhenDisabled"):
        if visual.get(key) is not False:
            raise DeliveryFailure("VISUAL_SIDE_EFFECT_DEFAULT_MUST_BE_CLOSED {0}".format(key))
    config = load_json(root / "packages/adapter-start-kit/config/adapter.example.json", "ADAPTER_EXAMPLE_CONFIG_MISSING")
    image = config.get("formatReview", {}).get("imageSemantics", {})
    if image.get("enabled") is not True or "wpsAcceptanceConfirmed" in image:
        raise DeliveryFailure("IMAGE_SEMANTICS_EXAMPLE_NOT_OPEN")
    adapter_root = root / "packages/adapter-start-kit/adapter_service"
    sys.path.insert(0, str(adapter_root))
    from app.services.word.image_semantics import collect_image_inventory, image_pixel_policy

    policy = image_pixel_policy(
        {"enabled": False},
        {"imageInputMode": "openai_image_url", "serviceBaseUrl": "https://example.invalid/v1"},
    )
    inventory = collect_image_inventory({"images": [{"imageId": "fixture", "captionStatus": "missing"}]})
    if policy.get("allowed") is not False or inventory.get("pixelExportCount") != 0 or inventory.get("pixelUploadCount") != 0:
        raise DeliveryFailure("VISUAL_CLOSED_SIDE_EFFECT_CONTRACT_FAILED")


def audit_candidate_note(root: Path, manifest: Dict) -> None:
    """Require a generated note whose identity matches the package manifest."""
    note = safe_path(root, "docs/v0252-delivery.md", "V0252_CANDIDATE_NOTE_MISSING")
    content = note.read_text(encoding="utf-8")
    for pattern in STALE_CANDIDATE_NOTE_PATTERNS:
        if pattern.search(content):
            raise DeliveryFailure("V0252_CANDIDATE_NOTE_STALE {0}".format(pattern.pattern))

    evidence = manifest.get("candidateEvidence", {})
    release_date = str(manifest.get("releaseDate", ""))
    source_commit = str(evidence.get("sourceCommit", ""))
    candidate_build_id = str(evidence.get("candidateBuildId", ""))
    archive_name = "ai-wps-phase1-delivery-{0}-{1}-v0252.tar.gz".format(
        release_date, source_commit[:7]
    )
    checksum_name = str(evidence.get("archiveChecksumFile", ""))
    required = (
        "v0.25.2-alpha",
        "ai-wps-phase1-delivery-<YYYYMMDD>-<SOURCE_COMMIT>-v0252.tar.gz",
        "Issue #59",
        "format_semantics.v1",
        "manual acceptance",
        "`{0}-{1}`".format(release_date, source_commit[:7]),
        "`{0}`".format(candidate_build_id),
        "`{0}`".format(source_commit),
        "`{0}`".format(archive_name),
        "`{0}`".format(checksum_name),
        "Automated status: `candidate`",
        "Target acceptance status: `manual-pending`",
    )
    for marker in required:
        if marker not in content:
            raise DeliveryFailure("V0252_CANDIDATE_NOTE_IDENTITY_MISSING {0}".format(marker))


def _candidate_context(content: str) -> str:
    lines = content.splitlines()
    if lines.count(CANONICAL_BASIC_INFO_HEADING) != 1:
        raise DeliveryFailure("V0252_TARGET_ACCEPTANCE_BASIC_INFO_HEADING_CARDINALITY_INVALID")
    if lines.count(CANONICAL_NEXT_HEADING) != 1:
        raise DeliveryFailure("V0252_TARGET_ACCEPTANCE_NEXT_HEADING_CARDINALITY_INVALID")
    begin_positions = [
        index for index, line in enumerate(lines) if line == CANDIDATE_CONTEXT_BEGIN
    ]
    end_positions = [
        index for index, line in enumerate(lines) if line == CANDIDATE_CONTEXT_END
    ]
    begin_count = len(begin_positions)
    end_count = len(end_positions)
    if begin_count == 0 or end_count == 0:
        raise DeliveryFailure("V0252_TARGET_ACCEPTANCE_CANDIDATE_CONTEXT_DELIMITER_MISSING")
    if begin_count != 1 or end_count != 1:
        raise DeliveryFailure("V0252_TARGET_ACCEPTANCE_CANDIDATE_CONTEXT_DELIMITER_DUPLICATE")
    begin = begin_positions[0]
    end = end_positions[0]
    if begin > end:
        raise DeliveryFailure("V0252_TARGET_ACCEPTANCE_CANDIDATE_CONTEXT_DELIMITER_ORDER_INVALID")
    section_start, section_end = _basic_information_bounds(content)
    line_offsets = [0]
    for line in content.splitlines(keepends=True):
        line_offsets.append(line_offsets[-1] + len(line))
    if (
        line_offsets[begin] < section_start
        or line_offsets[end + 1] > section_end
    ):
        raise DeliveryFailure("V0252_TARGET_ACCEPTANCE_CANDIDATE_CONTEXT_OUTSIDE_BASIC_INFO")
    return "\n".join(lines[begin + 1 : end])


def _validate_candidate_context(content: str, manifest: Dict) -> None:
    context = _candidate_context(content)
    section_start, section_end = _basic_information_bounds(content)
    basic_section = content[section_start:section_end]
    if any(pattern.search(basic_section) for pattern in CANDIDATE_CONTEXT_STALE_PATTERNS):
        raise DeliveryFailure("V0252_TARGET_ACCEPTANCE_CANDIDATE_CONTEXT_STALE_NARRATIVE")
    lines = _non_empty_lines(context)
    current_lines = [line for line in lines if line.startswith("- 当前自动化候选：")]
    if not current_lines:
        raise DeliveryFailure("V0252_TARGET_ACCEPTANCE_CURRENT_CANDIDATE_LINE_MISSING")
    if len(current_lines) != 1:
        raise DeliveryFailure("V0252_TARGET_ACCEPTANCE_CURRENT_CANDIDATE_LINE_DUPLICATE")

    evidence = manifest.get("candidateEvidence", {})
    source_commit = str(evidence.get("sourceCommit", ""))
    candidate_build_id = str(evidence.get("candidateBuildId", ""))
    release_date = str(manifest.get("releaseDate", ""))
    archive_name = "ai-wps-phase1-delivery-{0}-{1}-v0252.tar.gz".format(
        release_date, source_commit[:7]
    )
    checksum_name = str(evidence.get("archiveChecksumFile", ""))
    expected_current = (
        "- 当前自动化候选：`{short_source}`，状态为 `candidate`；"
        "candidateBuildId：`{candidate_build_id}`；源码提交：`{source_commit}`；"
        "归档：`{archive_name}`；校验文件：`{checksum_name}`；"
        "目标验收：`manual-pending`（Issue #59）"
    ).format(
        short_source=source_commit[:7],
        candidate_build_id=candidate_build_id,
        source_commit=source_commit,
        archive_name=archive_name,
        checksum_name=checksum_name,
    )
    if current_lines[0] != expected_current:
        raise DeliveryFailure("V0252_TARGET_ACCEPTANCE_CANDIDATE_IDENTITY_MISMATCH")

    previous = evidence.get("supersedes", {})
    if previous.get("status") == "candidate":
        expected_previous = (
            "- 0.25.1 产品候选：`{archive_name}`，SHA-256：`{archive_sha256}`；"
            "candidateBuildId：`{candidate_build_id}`，状态仍为 `candidate`，不是 0.25.2 当前候选"
        ).format(
            archive_name=str(previous.get("archiveName", "")),
            archive_sha256=str(previous.get("archiveSha256", "")),
            candidate_build_id=str(previous.get("candidateBuildId", "")),
        )
        previous_prefixes = ("- 0.25.1 产品候选：",)
    else:
        expected_previous = (
            "- 上一被拒绝归档：`{archive_name}`，SHA-256：`{archive_sha256}`；"
            "candidateBuildId：`{candidate_build_id}`，状态为 `rejected`"
        ).format(
            archive_name=str(previous.get("archiveName", "")),
            archive_sha256=str(previous.get("archiveSha256", "")),
            candidate_build_id=str(previous.get("candidateBuildId", "")),
        )
        previous_prefixes = ("- 上一被拒绝归档：", "- 被拒绝归档：")
    previous_lines = [
        line
        for line in lines
        if line.startswith(previous_prefixes)
    ]
    if not previous_lines:
        raise DeliveryFailure("V0252_TARGET_ACCEPTANCE_SUPERSEDED_LINE_MISSING")
    if len(previous_lines) != 1:
        raise DeliveryFailure("V0252_TARGET_ACCEPTANCE_SUPERSEDED_LINE_DUPLICATE")
    if previous_lines[0] != expected_previous:
        raise DeliveryFailure("V0252_TARGET_ACCEPTANCE_SUPERSEDED_IDENTITY_MISMATCH")

    state_lines = [line for line in lines if line.startswith("- 候选状态：")]
    if not state_lines:
        raise DeliveryFailure("V0252_TARGET_ACCEPTANCE_CANDIDATE_STATE_MISSING")
    if len(state_lines) != 1:
        raise DeliveryFailure("V0252_TARGET_ACCEPTANCE_CANDIDATE_STATE_DUPLICATE")
    expected_state = (
        "- 候选状态：当前归档是自动化门禁产生的当前候选；"
        "自动化门禁不等于目标机验收，Issue #59 仍为 `manual-pending`。"
    )
    if state_lines[0] != expected_state:
        raise DeliveryFailure("V0252_TARGET_ACCEPTANCE_CANDIDATE_STATE_MISMATCH")

    expected_lines = [expected_current, expected_previous, expected_state]
    if any(line not in expected_lines for line in lines):
        raise DeliveryFailure("V0252_TARGET_ACCEPTANCE_CANDIDATE_CONTEXT_UNKNOWN_LINE")
    if len(lines) != len(expected_lines):
        raise DeliveryFailure("V0252_TARGET_ACCEPTANCE_CANDIDATE_CONTEXT_LINE_CARDINALITY_INVALID")
    if lines != expected_lines:
        raise DeliveryFailure("V0252_TARGET_ACCEPTANCE_CANDIDATE_CONTEXT_ORDER_INVALID")
    _validate_basic_info_schema(content, expected_lines)


def audit_target_acceptance_record(root: Path, manifest: Dict) -> None:
    record = safe_path(
        root,
        "docs/v0252-target-machine-acceptance.md",
        "TARGET_ACCEPTANCE_RECORD_MISSING",
    )
    content = record.read_text(encoding="utf-8")
    required = (
        "Issue #59",
        "manual-pending",
        "60,000",
        "120,000",
        "取消",
        "只读",
        "图像语义补充",
        "不写入仓库",
    )
    for marker in required:
        if marker not in content:
            raise DeliveryFailure("TARGET_ACCEPTANCE_RECORD_INCOMPLETE {0}".format(marker))
    mandatory_heading = "## 必测项目"
    matrix_heading = "### v2 后台格式审查判定矩阵"
    if mandatory_heading not in content or matrix_heading not in content:
        raise DeliveryFailure("TARGET_ACCEPTANCE_RECORD_MANDATORY_SECTION_MISSING")
    mandatory_section = content.split(mandatory_heading, 1)[1].split(
        matrix_heading, 1
    )[0]
    numbered_rows = []
    result_rows = {}
    duplicate_rows = set()
    for line in mandatory_section.splitlines():
        fields = [field.strip() for field in line.strip().strip("|").split("|")]
        if not fields or not fields[0].isdigit():
            continue
        index = int(fields[0])
        status = fields[2].strip("`") if len(fields) >= 3 else ""
        numbered_rows.append((index, status))
        if index in result_rows:
            duplicate_rows.add(index)
        result_rows[index] = status
    extra_rows = sorted(
        {index for index, _status in numbered_rows if index not in set(range(1, 10))}
    )
    if extra_rows:
        raise DeliveryFailure(
            "TARGET_ACCEPTANCE_RECORD_MANDATORY_ROWS_EXTRA {0}".format(
                ",".join(str(index) for index in extra_rows)
            )
        )
    if duplicate_rows:
        raise DeliveryFailure(
            "TARGET_ACCEPTANCE_RECORD_MANDATORY_ROWS_DUPLICATE {0}".format(
                ",".join(str(index) for index in sorted(duplicate_rows))
            )
        )
    missing_rows = set(range(1, 10)) - set(result_rows)
    if missing_rows:
        raise DeliveryFailure(
            "TARGET_ACCEPTANCE_RECORD_MANDATORY_ROWS_MISSING {0}".format(
                ",".join(str(index) for index in sorted(missing_rows))
            )
        )
    non_pending_rows = [
        index
        for index, status in sorted(result_rows.items())
        if status != "manual-pending"
    ]
    if non_pending_rows:
        raise DeliveryFailure(
            "TARGET_ACCEPTANCE_RECORD_RESULTS_MUST_REMAIN_PENDING rows={0}".format(
                ",".join(str(index) for index in non_pending_rows)
            )
        )
    for marker in (
        "当前记录状态：`manual-pending`",
        "记录状态：`manual-pending`",
        "`60,000` 字符全文两遍抽取目标 ≤ 30 秒",
        "`120,000` 字符全文两遍抽取目标 ≤ 60 秒",
        "两遍指纹（内容哈希、结构哈希和格式/对象摘要）一致",
    ):
        if marker not in content:
            raise DeliveryFailure("TARGET_ACCEPTANCE_RECORD_INCOMPLETE {0}".format(marker))
    if manifest.get("targetAcceptanceIssue") != 59:
        raise DeliveryFailure("TARGET_ACCEPTANCE_ISSUE_MISMATCH")
    if manifest.get("targetAcceptance", {}).get("status") != "manual-pending":
        raise DeliveryFailure("TARGET_ACCEPTANCE_RECORD_STATUS_INVALID")

    _validate_candidate_context(content, manifest)

    evidence = manifest.get("candidateEvidence", {})
    source_commit = str(evidence.get("sourceCommit", ""))
    candidate_build_id = str(evidence.get("candidateBuildId", ""))
    archive_name = "ai-wps-phase1-delivery-{0}-{1}-v0252.tar.gz".format(
        manifest.get("releaseDate", ""), source_commit[:7]
    )
    checksum_name = str(evidence.get("archiveChecksumFile", ""))
    for marker in TARGET_ACCEPTANCE_MATRIX_MARKERS:
        if marker not in content:
            raise DeliveryFailure("V0252_TARGET_ACCEPTANCE_MATRIX_MISSING {0}".format(marker))

    status = load_json(
        root / "docs/v0252-candidate-status.json",
        "V0252_CANDIDATE_STATUS_MISSING",
    )
    records = [item for item in status.get("records", []) if isinstance(item, dict)]
    current = [item for item in records if item.get("candidateBuildId") == candidate_build_id]
    candidate_records = [item for item in records if item.get("status") == "candidate"]
    if len(candidate_records) != 1:
        raise DeliveryFailure(
            "V0252_TARGET_ACCEPTANCE_STATUS_CANDIDATE_CARDINALITY_INVALID"
        )
    if candidate_records[0].get("candidateBuildId") != candidate_build_id:
        raise DeliveryFailure(
            "V0252_TARGET_ACCEPTANCE_STATUS_CANDIDATE_IDENTITY_MISMATCH"
        )
    if (
        len(current) != 1
        or current[0].get("status") != "candidate"
        or current[0].get("sourceCommit") != source_commit
        or current[0].get("archiveName") != archive_name
        or current[0].get("archiveChecksumFile") != checksum_name
    ):
        raise DeliveryFailure("V0252_TARGET_ACCEPTANCE_CANDIDATE_IDENTITY_MISMATCH")

    delivery_note = safe_path(root, "docs/v0252-delivery.md", "V0252_CANDIDATE_NOTE_MISSING")
    delivery_content = delivery_note.read_text(encoding="utf-8")
    for marker in (
        "`{0}`".format(candidate_build_id),
        "`{0}`".format(source_commit),
        "`{0}`".format(archive_name),
        "`{0}`".format(checksum_name),
        "Automated status: `candidate`",
        "Target acceptance status: `manual-pending`",
    ):
        if marker not in delivery_content:
            raise DeliveryFailure("V0252_TARGET_ACCEPTANCE_CANDIDATE_IDENTITY_MISMATCH")


def audit_candidate_lineage(root: Path, manifest: Dict) -> None:
    status = load_json(
        root / "docs/v0252-candidate-status.json",
        "V0252_CANDIDATE_STATUS_MISSING",
    )
    if (
        status.get("schemaVersion") != 1
        or status.get("product") != "AI-WPS"
        or status.get("version") != VERSION
        or not isinstance(status.get("records"), list)
    ):
        raise DeliveryFailure("V0252_CANDIDATE_STATUS_INVALID")

    evidence = manifest.get("candidateEvidence", {})
    if evidence.get("automatedResult") != "candidate":
        raise DeliveryFailure("V0252_AUTOMATED_RESULT_MUST_REMAIN_CANDIDATE")
    current_build_id = evidence.get("candidateBuildId")
    source_commit = evidence.get("sourceCommit")
    version_rule = manifest.get("versionRule")
    release_date = str(manifest.get("releaseDate", ""))
    if not re.fullmatch(r"[0-9]{8}", release_date):
        raise DeliveryFailure("V0252_RELEASE_DATE_INVALID")
    try:
        datetime.strptime(release_date, "%Y%m%d")
    except ValueError as exc:
        raise DeliveryFailure("V0252_RELEASE_DATE_INVALID") from exc
    if version_rule != "AI-WPS-P1-WORD-EXCEL-PPT-0.25.2-{0}".format(release_date):
        raise DeliveryFailure("V0252_VERSION_RULE_DATE_MISMATCH")
    if (
        not isinstance(current_build_id, str)
        or not BUILD_ID_RE.fullmatch(current_build_id)
        or current_build_id != "{0}-{1}".format(version_rule, source_commit)
    ):
        raise DeliveryFailure("V0252_CANDIDATE_BUILD_ID_INVALID")

    superseded = evidence.get("supersedes", {})
    current_archive_name = (
        "ai-wps-phase1-delivery-{0}-{1}-v0252.tar.gz".format(
            release_date, str(source_commit)[:7]
        )
    )
    previous_archive_match = None
    if isinstance(superseded, dict):
        previous_archive_match = re.fullmatch(
            r"ai-wps-phase1-delivery-(?P<date>[0-9]{8})"
            r"(?:-(?P<source>[0-9a-f]{7}))?-v025(?P<series>[12])\.tar\.gz",
            str(superseded.get("archiveName", "")),
        )
    previous_series = previous_archive_match.group("series") if previous_archive_match else ""
    expected_previous_status = "candidate" if previous_series == "1" else "rejected"
    if (
        not isinstance(superseded, dict)
        or superseded.get("status") != expected_previous_status
        or not SHA256_RE.fullmatch(str(superseded.get("archiveSha256", "")))
        or previous_archive_match is None
        or not PREVIOUS_BUILD_ID_RE.fullmatch(
            str(superseded.get("candidateBuildId", ""))
        )
        or superseded.get("archiveName") == current_archive_name
        or not str(superseded.get("candidateBuildId", "")).startswith(
            "AI-WPS-P1-WORD-EXCEL-PPT-0.25.{0}-{1}".format(
                previous_series, previous_archive_match.group("date")
            )
        )
    ):
        raise DeliveryFailure("V0252_SUPERSEDED_CANDIDATE_INVALID")
    _archive_source_binding(
        str(superseded.get("archiveName", "")),
        superseded.get("sourceCommit", ""),
        superseded.get("candidateBuildId", ""),
        "V0252_SUPERSEDED_CANDIDATE_SOURCE_BINDING_INVALID",
    )

    records = [item for item in status["records"] if isinstance(item, dict)]
    candidate_records = [item for item in records if item.get("status") == "candidate"]
    if len(candidate_records) != 1:
        raise DeliveryFailure("V0252_CANDIDATE_STATUS_CANDIDATE_CARDINALITY_INVALID")
    if candidate_records[0].get("candidateBuildId") != current_build_id:
        raise DeliveryFailure("V0252_CANDIDATE_STATUS_CANDIDATE_IDENTITY_MISMATCH")
    rejected = [
        item
        for item in records
        if item.get("archiveName") == superseded.get("archiveName")
    ]
    if previous_series == "1":
        if rejected:
            raise DeliveryFailure("V0252_PREVIOUS_PRODUCT_CANDIDATE_MUST_NOT_ENTER_STATUS")
    else:
        if len(rejected) != 1 or rejected[0].get("status") != "rejected":
            raise DeliveryFailure("V0252_REJECTED_CANDIDATE_RECORD_MISSING")
        if rejected[0].get("candidateBuildId") != superseded.get("candidateBuildId"):
            raise DeliveryFailure("V0252_REJECTED_CANDIDATE_BUILD_ID_MISMATCH")
        if rejected[0].get("archiveSha256") != superseded.get("archiveSha256"):
            raise DeliveryFailure("V0252_REJECTED_CANDIDATE_DIGEST_MISMATCH")
        previous_archive_source = previous_archive_match.group("source")
        if previous_archive_source is not None and (
            rejected[0].get("sourceCommit") != superseded.get("sourceCommit")
        ):
            raise DeliveryFailure("V0252_REJECTED_CANDIDATE_SOURCE_COMMIT_MISMATCH")

    current = [item for item in records if item.get("candidateBuildId") == current_build_id]
    if len(current) != 1 or current[0].get("status") != "candidate":
        raise DeliveryFailure("V0252_CURRENT_CANDIDATE_RECORD_INVALID")
    if current[0].get("archiveName") != current_archive_name:
        raise DeliveryFailure("V0252_CURRENT_CANDIDATE_ARCHIVE_NAME_INVALID")
    if current[0].get("sourceCommit") != source_commit:
        raise DeliveryFailure("V0252_CURRENT_CANDIDATE_SOURCE_COMMIT_INVALID")
    if current[0].get("archiveChecksumFile") != evidence.get("archiveChecksumFile"):
        raise DeliveryFailure("V0252_CURRENT_CANDIDATE_CHECKSUM_REFERENCE_INVALID")


def plugin_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.glob("packages/wps-ai-assistant*/*")):
        if path.is_file() and path.suffix.lower() in {".html", ".js", ".json"}:
            yield path


def audit_plugin_cache_identity(root: Path, expected_version: str) -> None:
    manifests = sorted(root.glob("packages/wps-ai-assistant*/manifest.json"))
    expected_directories = {
        "wps-ai-assistant_1.0.0",
        "wps-ai-assistant-wpp_1.0.0",
        "wps-ai-assistant-et_1.0.0",
    }
    if {path.parent.name for path in manifests} != expected_directories:
        raise DeliveryFailure("PLUGIN_MANIFEST_COUNT_INVALID")
    for manifest_path in manifests:
        manifest = load_json(manifest_path, "PLUGIN_MANIFEST_INVALID")
        if manifest.get("version") != expected_version:
            raise DeliveryFailure("PLUGIN_VERSION_MISMATCH {0}".format(manifest_path.parent.name))
    seen_version = False
    for path in plugin_files(root):
        content = path.read_text(encoding="utf-8")
        if "0.23.1-alpha" in content or "0.25.0-alpha" in content or "0.25.1-alpha" in content:
            raise DeliveryFailure("PLUGIN_CACHE_OLD_VERSION {0}".format(path.name))
        if expected_version in content:
            seen_version = True
    if not seen_version:
        raise DeliveryFailure("PLUGIN_CACHE_VERSION_MISSING")


def audit_scope(actual: Set[str]) -> None:
    for relative in actual:
        normalized = relative.lower()
        if any(part in normalized for part in FORBIDDEN_SCOPE_PARTS):
            raise DeliveryFailure("FUTURE_SCOPE_ASSET_REJECTED {0}".format(relative))
        if "/preview" in normalized or normalized.startswith("preview/"):
            raise DeliveryFailure("PREVIEW_ASSET_REJECTED {0}".format(relative))


def audit(root: Path) -> None:
    manifest = load_json(root / "release-manifest.json", "RELEASE_MANIFEST_MISSING")
    allowlist = load_json(root / "release-allowlist.json", "RELEASE_ALLOWLIST_MISSING")
    if manifest.get("version") != VERSION or manifest.get("adapter", {}).get("version") != VERSION:
        raise DeliveryFailure("V0252_VERSION_MISMATCH")
    if allowlist.get("version") != VERSION:
        raise DeliveryFailure("V0252_ALLOWLIST_VERSION_MISMATCH")
    baseline = manifest.get("baseline", {})
    if baseline.get("acceptedVersion") != BASELINE_VERSION or baseline.get("sourceStatus") != "candidate":
        raise DeliveryFailure("V0251_CANDIDATE_BASELINE_REQUIRED")
    evidence = manifest.get("candidateEvidence", {})
    if not COMMIT_RE.fullmatch(str(evidence.get("sourceCommit", ""))):
        raise DeliveryFailure("V0252_SOURCE_COMMIT_MISSING")
    release_date = str(manifest.get("releaseDate", ""))
    expected_checksum_name = "ai-wps-phase1-delivery-{0}-{1}-v0252.tar.gz.sha256".format(
        release_date, str(evidence.get("sourceCommit", ""))[:7]
    )
    if evidence.get("archiveChecksumFile") != expected_checksum_name:
        raise DeliveryFailure("V0252_ARCHIVE_CHECKSUM_EVIDENCE_MISSING")
    if manifest.get("targetAcceptanceIssue") != 59 or manifest.get("targetAcceptance", {}).get("status") != "manual-pending":
        raise DeliveryFailure("ISSUE_59_MANUAL_ACCEPTANCE_REQUIRED")
    policy = manifest.get("deliveryPolicy", {})
    if (
        policy.get("status") != "candidate"
        or policy.get("auditScript") != "scripts/audit_delivery.py"
        or policy.get("candidateAuditScript") != "scripts/audit_v0252_delivery.py"
    ):
        raise DeliveryFailure("V0252_CANDIDATE_POLICY_INVALID")
    if manifest.get("formatReview", {}).get("enabledByDefault") is not True:
        raise DeliveryFailure("FORMAT_REVIEW_DEFAULT_MUST_BE_OPEN")
    # Validate the bounded acceptance context before lineage so malformed
    # packaged evidence fails at its trust boundary, not in a later relation.
    audit_target_acceptance_record(root, manifest)
    audit_candidate_lineage(root, manifest)
    audit_candidate_note(root, manifest)
    actual = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
    audit_scope(actual)
    audit_plugin_cache_identity(root, VERSION)
    audit_format_assets(root, manifest)
    audit_visual_default(root, manifest)
    audit_no_legacy_format_references(root)
    print("v0252_delivery_audit=passed status=candidate version={0}".format(VERSION))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("delivery_root", type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--checksum-file", type=Path)
    parser.add_argument("--expected-archive-name")
    args = parser.parse_args(argv)
    try:
        if (args.archive is None) != (args.checksum_file is None):
            raise DeliveryFailure("V0252_ARCHIVE_CHECKSUM_ARGUMENTS_INCOMPLETE")
        audit(args.delivery_root.resolve())
        if args.archive is not None and args.checksum_file is not None:
            audit_archive_checksum(
                args.archive.resolve(),
                args.checksum_file.resolve(),
                args.expected_archive_name,
            )
    except (DeliveryFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print("v0252_delivery_audit=failed {0}".format(exc))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
