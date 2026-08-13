"""Small, read-only algorithm seam adapted from the authorized WX source.

The source modules are listed in ``SOURCE_MANIFEST.json``.  This adapter keeps
their deterministic recognition behaviour but accepts plain WPS snapshot facts
instead of ``python-docx`` objects.  It deliberately has no template defaults:
expected values are supplied by an AI-WPS compiled rule pack.
"""

import re
from typing import Any, Dict, List, Optional, Set, Tuple


_ORDERED_FORMATS = {
    "decimal",
    "decimalzero",
    "lowerletter",
    "upperletter",
    "lowerroman",
    "upperroman",
}
_CAPTION_OBJECT_TYPES = {"figure", "table"}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _normalized(value: Any) -> str:
    return _text(value).casefold().replace(" ", "")


def _number(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def heading_hierarchy_warnings(heading_sequence: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return only observed hierarchy violations; never infer missing headings."""
    warnings = []
    if not heading_sequence:
        return warnings
    previous_level = _number(heading_sequence[0].get("level"))
    if previous_level > 1:
        warnings.append(
            {
                "type": "first_heading_below_level_one",
                "level": previous_level,
                "text": _text(heading_sequence[0].get("text")),
            }
        )
    for heading in heading_sequence[1:]:
        level = _number(heading.get("level"))
        if previous_level and level > previous_level + 1:
            warnings.append(
                {
                    "type": "heading_level_jump",
                    "previousLevel": previous_level,
                    "level": level,
                    "text": _text(heading.get("text")),
                }
            )
        previous_level = level
    return warnings


def classify_list_fact(fact: Dict[str, Any]) -> Dict[str, Any]:
    """Classify a list using numbering evidence, not a style-name default."""
    numbering = fact.get("numbering") if isinstance(fact.get("numbering"), dict) else {}
    num_fmt = _normalized(fact.get("numFmt") or numbering.get("numFmt"))
    level = max(1, min(9, _number(fact.get("level") or numbering.get("level"), 1)))
    level_text = _text(fact.get("lvlText") or numbering.get("lvlText"))
    style_name = _text(fact.get("styleName"))
    evidence = []
    if num_fmt in {"bullet", "none"}:
        list_type = "bullet" if num_fmt == "bullet" else "plain"
        evidence.append("numbering_format")
    elif num_fmt in _ORDERED_FORMATS:
        list_type = "numbered"
        evidence.append("ordered_numbering_format")
    else:
        marker = _text(fact.get("marker"))
        if re.match(r"^[（(]?\d+[）)]", marker):
            list_type = "numbered"
            evidence.append("visible_number_marker")
        elif re.match(r"^[（(]?[A-Za-z][）)]", marker):
            list_type = "numbered"
            evidence.append("visible_letter_marker")
        else:
            return {
                "role": "unknown",
                "listType": "unknown",
                "level": level,
                "evidence": ["missing_numbering_evidence"],
            }
    if level_text:
        evidence.append("level_text")
    if style_name:
        evidence.append("style_observed")
    role = "list{0}_{1}".format(level, list_type)
    return {
        "role": role,
        "listType": list_type,
        "level": level,
        "evidence": evidence,
    }


def _unique_cells(cells: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    unique = []
    for index, cell in enumerate(cells):
        key = (cell.get("row"), cell.get("column"), cell.get("cellId", index))
        if key in seen:
            continue
        seen.add(key)
        unique.append(cell)
    return unique


def _looks_like_code(text: str) -> bool:
    upper = text[:240].upper()
    if text.startswith(("{", "[", "<")):
        return True
    return any(
        marker in upper
        for marker in (
            "POST ",
            "GET ",
            "PUT ",
            "DELETE ",
            "HTTP/1.",
            "CONTENT-TYPE:",
            "<?XML",
        )
    ) or ("{" in text and '"' in text and ":" in text)


def classify_table_fact(fact: Dict[str, Any]) -> Dict[str, Any]:
    """Classify table semantics while requiring positive data-table evidence."""
    cells = _unique_cells(
        [cell for cell in fact.get("cells", []) if isinstance(cell, dict)]
    )
    texts = [_text(cell.get("text")) for cell in cells]
    evidence = []
    if fact.get("nestedTable") or fact.get("hasGraphics") or not any(texts):
        if fact.get("nestedTable"):
            evidence.append("nested_table")
        if fact.get("hasGraphics"):
            evidence.append("graphic_content")
        if not any(texts):
            evidence.append("no_text_content")
        return {
            "tableType": "layout",
            "captionEligible": False,
            "visualCellCount": len(cells),
            "evidence": evidence,
        }
    if any(_looks_like_code(text) for text in texts):
        return {
            "tableType": "code_sample",
            "captionEligible": False,
            "visualCellCount": len(cells),
            "evidence": ["code_payload_content"],
        }

    rows = {}
    for cell in cells:
        row = _number(cell.get("row"), 0)
        rows.setdefault(row, []).append(cell)
    row_values = [row for _, row in sorted(rows.items())]
    column_counts = [len(row) for row in row_values]
    has_header = bool(row_values and all(_text(cell.get("text")) for cell in row_values[0]))
    repeated_shape = len(row_values) >= 2 and len(set(column_counts)) == 1 and column_counts[0] >= 2
    if has_header and repeated_shape:
        return {
            "tableType": "data",
            "captionEligible": True,
            "visualCellCount": len(cells),
            "headerRows": 1,
            "evidence": ["header_row", "repeated_row_shape", "relational_table_shape"],
        }
    return {
        "tableType": "unknown",
        "captionEligible": False,
        "visualCellCount": len(cells),
        "evidence": ["insufficient_data_table_evidence"],
    }


def _caption_kind(text: str) -> str:
    if re.match(r"^图\s*\d+", text):
        return "figure"
    if re.match(r"^表\s*\d+", text):
        return "table"
    return "unknown"


def associate_captions(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Associate only a unique compatible adjacent object and caption."""
    results = []
    for index, block in enumerate(blocks):
        if block.get("type") != "caption":
            continue
        caption_type = _caption_kind(_text(block.get("text")))
        candidates = []
        for candidate_index in (index - 1, index + 1):
            if candidate_index < 0 or candidate_index >= len(blocks):
                continue
            candidate = blocks[candidate_index]
            if candidate.get("type") in _CAPTION_OBJECT_TYPES:
                if caption_type in {"unknown", candidate.get("type")}:
                    candidates.append((candidate_index, candidate))
        if len(candidates) == 1:
            results.append(
                {
                    "captionIndex": index,
                    "objectIndex": candidates[0][0],
                    "status": "associated",
                    "captionType": caption_type,
                }
            )
        elif len(candidates) > 1:
            results.append(
                {
                    "captionIndex": index,
                    "status": "ambiguous",
                    "captionType": caption_type,
                }
            )
        else:
            results.append(
                {
                    "captionIndex": index,
                    "status": "orphaned",
                    "captionType": caption_type,
                }
            )
    return results


def classify_appendix_fact(style_name: Any, text: Any) -> Optional[Dict[str, Any]]:
    style = _normalized(style_name)
    value = _text(text)
    if "附录标题" in style or re.match(r"^附\s*录(?:\s*[A-Z])?", value, re.IGNORECASE):
        return {"role": "appendix_title", "evidence": ["appendix_marker_or_style"]}
    match = re.match(r"^[A-Z]((?:[.]\d+){1,3})\s*", value, re.IGNORECASE)
    if match:
        level = min(3, match.group(1).count("."))
        return {
            "role": "appendix_heading{0}".format(level),
            "evidence": ["appendix_visible_heading_marker"],
        }
    return None


def classify_note_fact(style_name: Any, numbering: Optional[Dict[str, Any]], text: Any) -> Optional[str]:
    style = _normalized(style_name)
    if "注-有编号注" in style:
        return "numbered_note"
    if "注-无编号注" in style:
        return "note"
    numbering = numbering or {}
    level_text = _normalized(numbering.get("lvlText"))
    num_fmt = _normalized(numbering.get("numFmt"))
    if re.match(r"^注%?\d*[：:]$", level_text):
        return "numbered_note" if num_fmt in _ORDERED_FORMATS else "note"
    value = _text(text)
    if re.match(r"^注\s*\d+\s*[：:]", value):
        return "numbered_note"
    if re.match(r"^注\s*[：:]", value):
        return "note"
    return None


def _enabled_algorithms(pack: Dict[str, Any]) -> Set[str]:
    return {
        _text(rule.get("algorithm"))
        for rule in pack.get("rules", [])
        if isinstance(rule, dict) and rule.get("enabled")
    }


def audit_format_facts(facts: Dict[str, Any], pack: Dict[str, Any]) -> Dict[str, Any]:
    """Audit observed facts against compiled AI-WPS values and structure rules."""
    issues = []
    algorithms = _enabled_algorithms(pack)
    role_rules = pack.get("template", {}).get("roleRules", {})
    for paragraph in facts.get("paragraphs", []):
        if not isinstance(paragraph, dict):
            continue
        role = _text(paragraph.get("role")) or "body"
        expected = role_rules.get(role)
        if not isinstance(expected, dict):
            continue
        for field, label in (("fontName", "font_name"), ("fontSize", "font_size")):
            if field not in paragraph or field not in expected:
                continue
            if paragraph.get(field) != expected.get(field):
                issues.append(
                    {
                        "ruleId": label,
                        "role": role,
                        "currentValue": paragraph.get(field),
                        "expectedValue": expected.get(field),
                        "status": "violation",
                    }
                )
    if "heading_hierarchy" in algorithms:
        for warning in heading_hierarchy_warnings(facts.get("headings", [])):
            issues.append({"ruleId": "structure.heading_hierarchy", "status": "violation", **warning})
    tables = []
    if "table_semantics" in algorithms:
        tables = [classify_table_fact(table) for table in facts.get("tables", [])]
    captions = []
    if "caption_placement" in algorithms:
        captions = associate_captions(facts.get("blocks", []))
    lists = []
    if "list_semantics" in algorithms:
        lists = [classify_list_fact(item) for item in facts.get("lists", [])]
    appendix_roles = []
    if "appendix_roles" in algorithms:
        appendix_roles = [
            classified
            for item in facts.get("appendixFacts", [])
            for classified in [classify_appendix_fact(item.get("styleName"), item.get("text"))]
            if classified is not None
        ]
    note_roles = []
    if "note_roles" in algorithms:
        note_roles = [
            {"role": role}
            for item in facts.get("noteFacts", [])
            for role in [
                classify_note_fact(
                    item.get("styleName"), item.get("numbering"), item.get("text")
                )
            ]
            if role is not None
        ]
    return {
        "issues": issues,
        "tables": tables,
        "captions": captions,
        "lists": lists,
        "appendixRoles": appendix_roles,
        "noteRoles": note_roles,
    }
