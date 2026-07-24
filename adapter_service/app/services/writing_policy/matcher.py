import json
from collections import deque
from typing import Dict, Iterable, List, Sequence, Set, Tuple

from .models import (
    MAX_PROMPT_CHARS,
    MAX_STYLE_RULES,
    MAX_TERM_MATCHES,
    WritingPolicyMatchResult,
    normalize_key,
    public_usage,
)


_HEADER = "写作规范（必须遵守）："
_PRECEDENCE_LINES = (
    "[固定优先级]",
    "1. 保护项：原文中的事实、专有名词、数字、日期、责任主体、条款和规范性强度不得被下层要求改写。",
    "2. 用户本次明确要求：在不改变保护项的前提下，优先执行用户本次提出的目标、范围和格式要求。",
    "3. 组织层：组织术语和组织规则优先于产品预置规范。",
    "4. 预置层：按当前规范场景应用预置术语和文体规则。",
    "5. 通用去模板化规则：只优化表达，不得削弱正式度、事实、责任或规范性强度。",
)
_FOOTER = "以上规范不得要求新增原文不存在、用户也未要求的标题、列表、表格或事实。"
_REVIEW_INSTRUCTION = (
    "文档审查中，发现上述术语或写作规范违规时，必须按 professional 类问题报告。"
)
_PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}
_TERM_MATCH_STANDARD = 0
_TERM_MATCH_ALIAS = 1
_TERM_MATCH_FORBIDDEN = 2
_TERM_MATCH_NONE = 3
_MAX_INDEX_STATES = 100000
_RESERVED_STYLE_RULES = 5
_RESERVED_ANTI_TEMPLATE_RULES = 3


class _LiteralIndex:
    def __init__(self, token_targets: Dict[str, object]):
        transitions = [{}]
        failures = [0]
        terminals = [[]]
        failure_order = []
        self._token_count = 0

        for token, payloads in sorted(token_targets.items()):
            if not token:
                continue
            self._token_count += 1
            state = 0
            for character in token:
                next_state = transitions[state].get(character)
                if next_state is None:
                    next_state = len(transitions)
                    transitions[state][character] = next_state
                    transitions.append({})
                    failures.append(0)
                    terminals.append([])
                state = next_state
            terminals[state].extend(sorted(payloads))

        pending = deque(transitions[0].values())
        while pending:
            state = pending.popleft()
            failure_order.append(state)
            for character, next_state in transitions[state].items():
                fallback = failures[state]
                fallback_state = transitions[fallback].get(character)
                while fallback and fallback_state is None:
                    fallback = failures[fallback]
                    fallback_state = transitions[fallback].get(character)
                failures[next_state] = fallback_state or 0
                pending.append(next_state)

        self._transitions = transitions
        self._failures = failures
        self._terminals = terminals
        self._failure_order = failure_order
        self._terminal_payload_count = sum(
            len(payloads) for payloads in terminals
        )

    @property
    def state_count(self) -> int:
        return len(self._transitions)

    @property
    def token_count(self) -> int:
        return self._token_count

    @property
    def terminal_payload_count(self) -> int:
        return self._terminal_payload_count

    def matched_payloads(self, text: str) -> List[object]:
        transitions = self._transitions
        failures = self._failures
        terminals = self._terminals
        visited = bytearray(len(transitions))
        state = 0
        for character in text:
            next_state = transitions[state].get(character)
            while state and next_state is None:
                state = failures[state]
                next_state = transitions[state].get(character)
            state = next_state or 0
            visited[state] = 1

        for state in reversed(self._failure_order):
            if visited[state]:
                visited[failures[state]] = 1

        matches = []
        for state, payloads in enumerate(terminals):
            if visited[state]:
                matches.extend(payloads)
        return matches


def _source_text(source_parts: Sequence[str]) -> str:
    return normalize_key(" ".join(part for part in source_parts if part))


def _source_prefix_windows(
    source_text: str,
) -> Tuple[Set[str], Set[str], Set[str]]:
    windows = [set(source_text)]
    for width in (4, 8):
        if len(source_text) < width:
            windows.append(set())
            continue
        windows.append(
            {
                source_text[index : index + width]
                for index in range(len(source_text) - width + 1)
            }
        )
    return windows[0], windows[1], windows[2]


def _has_source_prefix(
    token: str, source_windows: Tuple[Set[str], Set[str], Set[str]]
) -> bool:
    if len(token) >= 8:
        return token[:8] in source_windows[2]
    if len(token) >= 4:
        return token[:4] in source_windows[1]
    return token[0] in source_windows[0]


def _common_prefix_length(left: str, right: str) -> int:
    limit = min(len(left), len(right))
    index = 0
    while index < limit and left[index] == right[index]:
        index += 1
    return index


def _token_batches(
    token_targets: Dict[str, object],
    source_windows: Tuple[Set[str], Set[str], Set[str]],
) -> Iterable[Dict[str, object]]:
    batch = {}
    estimated_states = 0
    previous_token = ""
    filtered_targets = (
        (token, payloads)
        for token, payloads in token_targets.items()
        if _has_source_prefix(token, source_windows)
    )
    for token, payloads in sorted(filtered_targets):
        added_states = len(token) - _common_prefix_length(previous_token, token)
        if batch and estimated_states + added_states > _MAX_INDEX_STATES:
            yield batch
            batch = {}
            estimated_states = 0
            previous_token = ""
            added_states = len(token)
        batch[token] = payloads
        estimated_states += added_states
        previous_token = token
    if batch:
        yield batch


def _matched_payloads(
    token_targets: Dict[str, object],
    source_text: str,
    source_windows: Tuple[Set[str], Set[str], Set[str]],
) -> Iterable[object]:
    for batch in _token_batches(token_targets, source_windows):
        literal_index = _LiteralIndex(batch)
        for payload in literal_index.matched_payloads(source_text):
            yield payload


def _values(item: Dict, key: str) -> List[str]:
    values = item.get(key) or []
    return [str(value) for value in values if str(value).strip()]


def _priority_rank(item: Dict) -> int:
    return _PRIORITY_RANK.get(str(item.get("priority", "")), len(_PRIORITY_RANK))


def _normalized_payload(value: object) -> object:
    if isinstance(value, dict):
        return {
            str(key): _normalized_payload(item_value)
            for key, item_value in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_normalized_payload(item_value) for item_value in value]
    if isinstance(value, str):
        return normalize_key(value)
    return value


def _payload_sort_key(item: Dict) -> Tuple[str, str]:
    options = {
        "ensure_ascii": False,
        "sort_keys": True,
        "separators": (",", ":"),
        "default": str,
    }
    normalized = json.dumps(_normalized_payload(item), **options)
    original = json.dumps(item, **options)
    return normalized, original


def _term_sort_key(item: Dict, match_class: int) -> Tuple[object, ...]:
    return (
        _term_precedence_rank(item),
        match_class,
        _priority_rank(item),
        normalize_key(str(item.get("preferredText", ""))),
        str(item.get("id", "")),
        _payload_sort_key(item),
    )


def _term_precedence_rank(item: Dict) -> int:
    layer = item.get("layer")
    return 0 if layer == "organization" or (not layer and not item.get("packId")) else 1


def _style_sort_key(item: Dict, task_scope: str) -> Tuple[object, ...]:
    return (
        _style_precedence_rank(item),
        0 if item.get("scope") == task_scope else 1,
        0 if bool(item.get("alwaysApply", False)) else 1,
        _priority_rank(item),
        normalize_key(str(item.get("name", ""))),
        str(item.get("id", "")),
        _payload_sort_key(item),
    )


def _style_precedence_rank(item: Dict) -> int:
    category = normalize_key(str(item.get("category", "")))
    if "保护" in category:
        return 0
    layer = item.get("layer")
    if layer == "organization" or (not layer and not item.get("packId")):
        return 1
    if item.get("type") == "anti_template":
        return 3
    return 2


def _select_rule_candidates(matched_styles: Sequence[Dict]) -> List[Dict]:
    selected = [
        item
        for item in matched_styles
        if _style_precedence_rank(item) <= 1
    ][:MAX_STYLE_RULES]
    selected_ids = {id(item) for item in selected}
    remaining_slots = MAX_STYLE_RULES - len(selected)
    if remaining_slots <= 0:
        return selected

    lower_precedence = [
        item for item in matched_styles if id(item) not in selected_ids
    ]
    style_count = sum(item.get("type") != "anti_template" for item in selected)
    anti_template_count = len(selected) - style_count
    style_slots = max(0, _RESERVED_STYLE_RULES - style_count)
    anti_template_slots = max(
        0,
        _RESERVED_ANTI_TEMPLATE_RULES - anti_template_count,
    )

    for item in lower_precedence:
        is_anti_template = item.get("type") == "anti_template"
        if is_anti_template and anti_template_slots > 0:
            selected.append(item)
            selected_ids.add(id(item))
            anti_template_slots -= 1
            remaining_slots -= 1
        elif not is_anti_template and style_slots > 0:
            selected.append(item)
            selected_ids.add(id(item))
            style_slots -= 1
            remaining_slots -= 1
        if remaining_slots == 0:
            break

    if remaining_slots > 0:
        for item in lower_precedence:
            if id(item) in selected_ids:
                continue
            selected.append(item)
            selected_ids.add(id(item))
            remaining_slots -= 1
            if remaining_slots == 0:
                break
    return [
        item for item in matched_styles if id(item) in selected_ids
    ]


def _add_term_tokens(
    token_targets: Dict[str, object], item: Dict, candidate_index: int
) -> None:
    item_id = str(item.get("id", ""))
    groups = (
        (_TERM_MATCH_STANDARD, [str(item.get("preferredText", ""))]),
        (_TERM_MATCH_ALIAS, _values(item, "aliases")),
        (_TERM_MATCH_FORBIDDEN, _values(item, "forbiddenVariants")),
    )
    for match_class, values in groups:
        for value in values:
            token = normalize_key(value)
            if token:
                token_targets.setdefault(token, set()).add(
                    (item_id, match_class, candidate_index)
                )


def _term_forms(item: Dict) -> set:
    values = (
        [str(item.get("preferredText", ""))]
        + _values(item, "aliases")
        + _values(item, "forbiddenVariants")
    )
    return {normalize_key(value) for value in values if normalize_key(value)}


def _add_style_tokens(
    token_targets: Dict[str, object], item: Dict, candidate_index: int
) -> None:
    for value in _values(item, "contextKeywords"):
        token = normalize_key(value)
        if token:
            token_targets.setdefault(token, set()).add((candidate_index,))


def match_writing_policy(
    terms: Sequence[Dict],
    styles: Sequence[Dict],
    task_scope: str,
    source_parts: Sequence[str],
) -> Tuple[List[Dict], List[Dict]]:
    source_text = _source_text(source_parts)
    source_windows = _source_prefix_windows(source_text)

    candidate_terms = []
    for term in terms:
        if not bool(term.get("enabled", True)):
            continue
        candidate_terms.append(term)

    token_targets = {}
    for candidate_index, term in enumerate(candidate_terms):
        _add_term_tokens(token_targets, term, candidate_index)

    best_match_by_candidate = {}
    for _item_id, match_class, candidate_index in _matched_payloads(
        token_targets, source_text, source_windows
    ):
        previous = best_match_by_candidate.get(candidate_index, _TERM_MATCH_NONE)
        if match_class < previous:
            best_match_by_candidate[candidate_index] = match_class

    term_candidates = [
        (candidate_terms[candidate_index], match_class)
        for candidate_index, match_class in best_match_by_candidate.items()
    ]
    term_candidates.sort(key=lambda value: _term_sort_key(value[0], value[1]))

    matched_terms = []
    seen_term_ids = set()
    claimed_term_form_ranks = {}
    for term, _match_class in term_candidates:
        item_id = str(term.get("id", ""))
        term_forms = _term_forms(term)
        precedence_rank = _term_precedence_rank(term)
        if item_id in seen_term_ids or any(
            claimed_term_form_ranks.get(form, precedence_rank) < precedence_rank
            for form in term_forms
        ):
            continue
        matched_terms.append(term)
        seen_term_ids.add(item_id)
        for form in term_forms:
            claimed_term_form_ranks[form] = min(
                precedence_rank,
                claimed_term_form_ranks.get(form, precedence_rank),
            )

    relevant_styles = [
        style
        for style in styles
        if bool(style.get("enabled", True))
        and style.get("scope") in ("global", task_scope)
    ]
    styles_by_name = {}
    for style in relevant_styles:
        name_key = normalize_key(str(style.get("name", "")))
        current = styles_by_name.get(name_key)
        if current is None or _style_sort_key(
            style,
            task_scope,
        ) < _style_sort_key(current, task_scope):
            styles_by_name[name_key] = style
    candidate_styles = list(styles_by_name.values())
    qualified_style_indexes = {
        candidate_index
        for candidate_index, style in enumerate(candidate_styles)
        if bool(style.get("alwaysApply", False))
    }
    style_token_targets = {}
    for candidate_index, style in enumerate(candidate_styles):
        if not bool(style.get("alwaysApply", False)):
            _add_style_tokens(style_token_targets, style, candidate_index)
    for (candidate_index,) in _matched_payloads(
        style_token_targets, source_text, source_windows
    ):
        qualified_style_indexes.add(candidate_index)

    style_candidates = [
        candidate_styles[candidate_index]
        for candidate_index in qualified_style_indexes
    ]
    style_candidates.sort(key=lambda item: _style_sort_key(item, task_scope))

    matched_styles = []
    seen_style_ids = set()
    seen_style_names = set()
    for style in style_candidates:
        item_id = str(style.get("id", ""))
        normalized_name = normalize_key(str(style.get("name", "")))
        if item_id in seen_style_ids or normalized_name in seen_style_names:
            continue
        matched_styles.append(style)
        seen_style_ids.add(item_id)
        seen_style_names.add(normalized_name)

    return matched_terms, matched_styles


def _quoted_values(values: Sequence[str]) -> str:
    return "、".join("“%s”" % value for value in values)


def _render_term(item: Dict) -> str:
    preferred = str(item.get("preferredText", ""))
    parts = ["- 统一使用标准写法“%s”" % preferred]
    aliases = _values(item, "aliases")
    forbidden = _values(item, "forbiddenVariants")
    definition = str(item.get("definition", "")).strip()
    if aliases:
        parts.append("别名%s出现时改为该标准写法" % _quoted_values(aliases))
    if forbidden:
        parts.append("禁用写法%s不得使用，出现时改为该标准写法" % _quoted_values(forbidden))
    if definition:
        parts.append("定义：%s" % definition)
    return "；".join(parts) + "。"


def _render_style(item: Dict) -> str:
    name = str(item.get("name", ""))
    rule_text = str(item.get("ruleText", "")).strip()
    lines = ["- %s：%s" % (name, rule_text)]
    positive = str(item.get("positiveExample", "")).strip()
    negative = str(item.get("negativeExample", "")).strip()
    if positive:
        lines.append("  推荐：%s" % positive)
    if negative:
        lines.append("  避免：%s" % negative)
    return "\n".join(lines)


def _compose_prompt(
    term_entries: Sequence[str],
    style_entries: Sequence[str],
    anti_template_entries: Sequence[str],
    task_scope: str,
) -> str:
    parts = [_HEADER]
    parts.extend(_PRECEDENCE_LINES)
    if term_entries:
        parts.extend(("", "[术语]"))
        parts.extend(term_entries)
    if style_entries:
        parts.extend(("", "[文体]"))
        parts.extend(style_entries)
    if anti_template_entries:
        parts.extend(("", "[去模板化]"))
        parts.extend(anti_template_entries)
    if task_scope == "word.document_review":
        parts.extend(("", _REVIEW_INSTRUCTION))
    parts.extend(("", _FOOTER))
    return "\n".join(parts)


def build_match_result(
    terms: Sequence[Dict],
    styles: Sequence[Dict],
    task_scope: str,
    source_parts: Sequence[str],
) -> WritingPolicyMatchResult:
    matched_terms, matched_styles = match_writing_policy(
        terms, styles, task_scope, source_parts
    )
    if not matched_terms and not matched_styles:
        usage = public_usage(
            applied=True,
            terms=0,
            styles=0,
            anti_templates=0,
            truncated=0,
            matched_items=[],
        )
        return WritingPolicyMatchResult("", usage, (), audit_terms=())

    term_candidates = matched_terms[:MAX_TERM_MATCHES]
    style_candidates = _select_rule_candidates(matched_styles)
    truncated = (
        len(matched_terms)
        - len(term_candidates)
        + len(matched_styles)
        - len(style_candidates)
    )

    included_terms = []
    included_term_entries = []
    included_styles = []
    included_style_entries = []
    included_anti_templates = []
    included_anti_template_entries = []
    character_budget_exhausted = False

    for term in term_candidates:
        if character_budget_exhausted:
            truncated += 1
            continue
        entry = _render_term(term)
        candidate_prompt = _compose_prompt(
            included_term_entries + [entry],
            included_style_entries,
            included_anti_template_entries,
            task_scope,
        )
        if len(candidate_prompt) > MAX_PROMPT_CHARS:
            truncated += 1
            character_budget_exhausted = True
            continue
        included_terms.append(term)
        included_term_entries.append(entry)

    for style in style_candidates:
        if character_budget_exhausted:
            truncated += 1
            continue
        entry = _render_style(style)
        is_anti_template = style.get("type") == "anti_template"
        candidate_prompt = _compose_prompt(
            included_term_entries,
            included_style_entries + ([] if is_anti_template else [entry]),
            included_anti_template_entries + ([entry] if is_anti_template else []),
            task_scope,
        )
        if len(candidate_prompt) > MAX_PROMPT_CHARS:
            truncated += 1
            character_budget_exhausted = True
            continue
        if is_anti_template:
            included_anti_templates.append(style)
            included_anti_template_entries.append(entry)
        else:
            included_styles.append(style)
            included_style_entries.append(entry)

    prompt_block = _compose_prompt(
        included_term_entries,
        included_style_entries,
        included_anti_template_entries,
        task_scope,
    )
    public_items = [
        {"id": item.get("id"), "type": "term", "name": item.get("preferredText")}
        for item in included_terms
    ] + [
        {"id": item.get("id"), "type": "style", "name": item.get("name")}
        for item in included_styles
    ] + [
        {
            "id": item.get("id"),
            "type": "anti_template",
            "name": item.get("name"),
        }
        for item in included_anti_templates
    ]
    usage = public_usage(
        applied=True,
        terms=len(included_terms),
        styles=len(included_styles),
        anti_templates=len(included_anti_templates),
        truncated=truncated,
        matched_items=public_items,
    )
    matched_item_ids = tuple(str(item.get("id", "")) for item in included_terms)
    matched_item_ids += tuple(str(item.get("id", "")) for item in included_styles)
    matched_item_ids += tuple(
        str(item.get("id", "")) for item in included_anti_templates
    )
    return WritingPolicyMatchResult(
        prompt_block,
        usage,
        matched_item_ids,
        audit_terms=term_candidates,
    )
