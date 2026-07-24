import re
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple

from .models import normalize_key


MAX_AUDIT_FINDINGS = 12
MAX_EVIDENCE_CHARS = 80

_DATE_RE = re.compile(
    r"(?:20\d{2}[-/.年](?:0?[1-9]|1[0-2])[-/.月](?:0?[1-9]|[12]\d|3[01])日?)"
)
_STANDARD_RE = re.compile(
    r"(?:GB(?:/T)?|GA/T|ISO(?:/IEC)?)\s*[A-Za-z0-9.-]+(?:—|-)\d{4}",
    re.IGNORECASE,
)
_CLAUSE_RE = re.compile(r"第[一二三四五六七八九十百千万0-9]+条")
_NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9])\d+(?:\.\d+)?(?:%|％|项|个|次|人|户|台|套|天|日|月|年|小时|分钟|秒)?"
)
_RESPONSIBILITY_RE = re.compile(
    r"(?:^|[，。；;,\n])"
    r"([一-龥A-Za-z0-9（）()·]{2,24}?)"
    r"(?=(?:负责|牵头|承办|配合|审核|复核|验收|整改))"
)
_QUOTED_PROPER_NOUN_RE = re.compile(r"[“\"]([^”\"\n]{2,40})[”\"]")
_NAMED_ENTITY_RE = re.compile(
    r"(?:^|[，。；：、\s]|采用|使用|部署|建设|依托|基于|升级|改造|维护|运行|接入|开发)"
    r"([一-龥A-Za-z0-9·_-]{2,24}?(?:系统|平台|项目|工程|公司|集团|中心|产品))"
)
_IDENTIFIER_RE = re.compile(
    r"(?<![A-Za-z0-9])(?=[A-Za-z0-9_.-]{3,40}(?![A-Za-z0-9_.-]))"
    r"(?=[A-Za-z0-9_.-]*[A-Za-z])(?=[A-Za-z0-9_.-]*\d)"
    r"[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)+(?![A-Za-z0-9_.-])"
)
_NORMATIVE_WORDS = ("必须", "不得", "严禁", "应", "可以", "建议")
_T1_PATTERNS = (
    ("值得注意的是", re.compile(r"值得注意的是")),
    ("需要指出的是", re.compile(r"需要指出的是")),
    ("毋庸置疑", re.compile(r"毋庸置疑")),
    ("形势铺垫", re.compile(r"在.{0,24}(?:背景|形势|浪潮)下")),
    ("宣传性收束", re.compile(r"(?:崭新局面|全新篇章|新的历史起点)")),
)
_T2_PATTERNS = (
    ("不仅—更", re.compile(r"不仅.{0,40}(?:更|而且)")),
    ("从—到—再到", re.compile(r"从.{0,24}到.{0,24}再到")),
    ("既—又—还", re.compile(r"既.{0,24}又.{0,24}还")),
    ("赋能式表达", re.compile(r"(?:赋能|全面领先|彻底解决|跨越式提升)")),
)
_T3_MARKERS = ("首先", "其次", "再次", "最后", "一方面", "另一方面")


def _evidence(value: object) -> str:
    return str(value or "").strip().replace("\n", " ")[:MAX_EVIDENCE_CHARS]


def _append_unique(
    findings: List[Dict[str, object]],
    seen: set,
    *,
    code: str,
    label: str,
    message: str,
    evidence: str,
    tier: str = "",
) -> None:
    if len(findings) >= MAX_AUDIT_FINDINGS:
        return
    key = (code, normalize_key(evidence))
    if key in seen:
        return
    seen.add(key)
    finding = {
        "code": code,
        "label": label,
        "message": message,
        "evidence": _evidence(evidence),
    }
    if tier:
        finding["tier"] = tier
    findings.append(finding)


def _tokens(pattern: re.Pattern, text: str) -> Tuple[str, ...]:
    return tuple(match.group(0) for match in pattern.finditer(text))


def _changed_values(
    source: str,
    result: str,
    pattern: re.Pattern,
) -> Iterable[str]:
    result_values = {normalize_key(value) for value in _tokens(pattern, result)}
    for value in _tokens(pattern, source):
        if normalize_key(value) not in result_values:
            yield value


def _responsibility_subjects(text: str) -> Tuple[str, ...]:
    return tuple(match.group(1) for match in _RESPONSIBILITY_RE.finditer(text))


def _protected_proper_nouns(text: str) -> Tuple[str, ...]:
    values = [
        match.group(1)
        for pattern in (_QUOTED_PROPER_NOUN_RE, _NAMED_ENTITY_RE)
        for match in pattern.finditer(text)
    ]
    return tuple(dict.fromkeys(values))


def _audit_protected_values(
    source: str,
    result: str,
    findings: List[Dict[str, object]],
    seen: set,
) -> None:
    groups = (
        (
            _DATE_RE,
            "protected_date_changed",
            "日期发生变化",
            "原文日期未在结果中保持，请核对时间边界。",
        ),
        (
            _STANDARD_RE,
            "protected_standard_changed",
            "标准编号发生变化",
            "原文标准编号未在结果中保持，请核对引用依据。",
        ),
        (
            _CLAUSE_RE,
            "protected_clause_changed",
            "条款编号发生变化",
            "原文条款编号未在结果中保持，请核对条款引用。",
        ),
        (
            _NUMBER_RE,
            "protected_number_changed",
            "数字或数量发生变化",
            "原文数字、数量或单位未在结果中保持，请核对事实口径。",
        ),
    )
    for pattern, code, label, message in groups:
        for value in _changed_values(source, result, pattern):
            _append_unique(
                findings,
                seen,
                code=code,
                label=label,
                message=message,
                evidence=value,
            )

    source_subjects = {
        normalize_key(value): value for value in _responsibility_subjects(source)
    }
    result_subjects = {
        normalize_key(value) for value in _responsibility_subjects(result)
    }
    for key, value in source_subjects.items():
        if key not in result_subjects:
            _append_unique(
                findings,
                seen,
                code="responsibility_subject_changed",
                label="责任主体发生变化",
                message="原文责任主体未在结果中保持，请核对责任边界。",
                evidence=value,
            )

    result_proper_nouns = {
        normalize_key(value) for value in _protected_proper_nouns(result)
    }
    for value in _protected_proper_nouns(source):
        if normalize_key(value) not in result_proper_nouns:
            _append_unique(
                findings,
                seen,
                code="protected_proper_noun_changed",
                label="专有名词发生变化",
                message="原文明示的系统、平台、项目或其他专名未在结果中保持，请核对事实。",
                evidence=value,
            )

    for value in _changed_values(source, result, _IDENTIFIER_RE):
        _append_unique(
            findings,
            seen,
            code="protected_identifier_changed",
            label="标识符发生变化",
            message="原文型号、版本或其他字母数字标识未在结果中保持，请核对事实。",
            evidence=value,
        )

    for word in _NORMATIVE_WORDS:
        if source.count(word) > result.count(word):
            _append_unique(
                findings,
                seen,
                code="normative_strength_changed",
                label="规范性强度发生变化",
                message="原文规范性词在结果中减少，请核对要求强度。",
                evidence=word,
            )


def _audit_terms(
    source: str,
    result: str,
    terms: Sequence[Mapping[str, object]],
    findings: List[Dict[str, object]],
    seen: set,
) -> None:
    normalized_source = normalize_key(source)
    normalized_result = normalize_key(result)
    for term in terms:
        preferred = str(term.get("preferredText", "")).strip()
        if not preferred:
            continue
        aliases = [
            str(value).strip()
            for value in term.get("aliases", []) or []
            if str(value).strip()
        ]
        forbidden = [
            str(value).strip()
            for value in term.get("forbiddenVariants", []) or []
            if str(value).strip()
        ]
        for value in forbidden:
            if normalize_key(value) in normalized_result:
                _append_unique(
                    findings,
                    seen,
                    code="nonstandard_term",
                    label="出现非标准术语",
                    message="结果中出现禁用或非标准写法，请核对并统一术语。",
                    evidence=value,
                )
        source_forms = [preferred] + aliases + forbidden
        if any(normalize_key(value) in normalized_source for value in source_forms):
            if normalize_key(preferred) not in normalized_result:
                _append_unique(
                    findings,
                    seen,
                    code="standard_term_changed",
                    label="标准术语发生变化",
                    message="已匹配的标准术语未在结果中保持，请核对术语口径。",
                    evidence=preferred,
                )


def _audit_expression_patterns(
    result: str,
    findings: List[Dict[str, object]],
    seen: set,
) -> None:
    for label, pattern in _T1_PATTERNS:
        match = pattern.search(result)
        if match:
            _append_unique(
                findings,
                seen,
                code="template_expression_t1",
                label=label,
                message="该表达具有明确模板化特征，可在不改变事实和责任的前提下改得更直接。",
                evidence=match.group(0),
                tier="T1",
            )
    for label, pattern in _T2_PATTERNS:
        match = pattern.search(result)
        if match:
            _append_unique(
                findings,
                seen,
                code="template_expression_t2",
                label=label,
                message="该句式较密集，可检查是否存在同义重复或信息空转。",
                evidence=match.group(0),
                tier="T2",
            )
    marker_count = sum(result.count(marker) for marker in _T3_MARKERS)
    if marker_count >= 3:
        _append_unique(
            findings,
            seen,
            code="template_expression_t3",
            label="机械化路标密集",
            message="段落路标词较密集，可按真实信息关系合并或改写。",
            evidence="、".join(
                marker for marker in _T3_MARKERS if marker in result
            ),
            tier="T3",
        )


def audit_writing_policy_result(
    source_text: str,
    result_text: str,
    matched_terms: Sequence[Mapping[str, object]],
) -> Dict[str, object]:
    source = str(source_text or "")
    result = str(result_text or "")
    needs_review = []  # type: List[Dict[str, object]]
    suggestions = []  # type: List[Dict[str, object]]
    _audit_protected_values(source, result, needs_review, set())
    _audit_terms(source, result, matched_terms, needs_review, set())
    _audit_expression_patterns(result, suggestions, set())

    if needs_review:
        summary = "写作规范检查发现需要人工核对的内容。"
    elif suggestions:
        summary = "写作规范检查提供了表达优化建议。"
    else:
        summary = "已完成写作规范检查"
    return {
        "passed": not needs_review and not suggestions,
        "degraded": False,
        "degradedReason": "",
        "summary": summary,
        "needsReview": needs_review,
        "expressionSuggestions": suggestions,
    }
