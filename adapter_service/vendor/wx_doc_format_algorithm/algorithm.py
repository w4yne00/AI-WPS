"""Small, read-only algorithm seam adapted from the authorized WX source.

The source modules are listed in ``SOURCE_MANIFEST.json``.  This adapter keeps
their deterministic recognition behaviour but accepts plain WPS snapshot facts
instead of ``python-docx`` objects.  It deliberately has no template defaults:
expected values are supplied by an AI-WPS compiled rule pack.
"""

import re
from copy import deepcopy
from typing import Any, Dict, List, Optional, Set, Tuple

from app.core.outline_level import normalize_heading_level, normalize_outline_level


_ORDERED_FORMATS = {
    "decimal",
    "decimalzero",
    "lowerletter",
    "upperletter",
    "lowerroman",
    "upperroman",
}
_CAPTION_OBJECT_TYPES = {"figure", "table"}
_CAPTION_MAX_DISTANCE = 3
_SEMANTIC_ROLES = {
    "document_title",
    "heading",
    "body",
    "list_item",
    "note",
    "caption",
    "toc_title",
    "toc_entry",
    "appendix_title",
    "appendix_heading",
    "formula",
    "table_body",
    "unknown",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _normalized(value: Any) -> str:
    return _text(value).casefold().replace(" ", "")


def _number(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _outline_fact(fact: Dict[str, Any]) -> Tuple[Optional[int], bool]:
    if "outlineLevel" in fact:
        return normalize_outline_level(fact.get("outlineLevel")), True
    if "headingLevel" in fact:
        return normalize_outline_level(fact.get("headingLevel")), True
    return None, False


def _legacy_role(role: Any) -> Optional[Dict[str, Any]]:
    value = _text(role)
    if value in _SEMANTIC_ROLES:
        return {"role": value, "attributes": {}}
    match = re.fullmatch(r"heading([1-9])", value)
    if match:
        return {"role": "heading", "attributes": {"level": int(match.group(1))}}
    match = re.fullmatch(r"list([1-9])_(numbered|plain)", value)
    if match:
        return {
            "role": "list_item",
            "attributes": {"level": int(match.group(1)), "ordered": match.group(2) == "numbered"},
        }
    match = re.fullmatch(r"appendix_heading([1-9])", value)
    if match:
        return {"role": "appendix_heading", "attributes": {"level": int(match.group(1))}}
    if value == "numbered_note":
        return {"role": "note", "attributes": {"numbered": True}}
    return None


def classify_role_fact(fact: Dict[str, Any]) -> Dict[str, Any]:
    """Classify a semantic role from structural evidence, never from style alone."""
    if not isinstance(fact, dict):
        return {"role": "unknown", "attributes": {}, "status": "needs_confirmation", "evidence": []}

    candidates: Dict[str, Dict[str, Any]] = {}
    evidence: Dict[str, List[str]] = {}

    def add(role: str, source: str, attributes: Optional[Dict[str, Any]] = None) -> None:
        if role not in _SEMANTIC_ROLES or role == "unknown":
            return
        candidates.setdefault(role, {})
        if attributes:
            candidates[role].update(attributes)
        evidence.setdefault(role, []).append(source)

    explicit = None
    for key in ("semanticRole", "structuralRole", "roleFact", "fieldRole"):
        value = fact.get(key)
        if isinstance(value, dict):
            value = value.get("role")
        if value:
            explicit = _legacy_role(value)
            if explicit:
                add(explicit["role"], "structural_role", explicit.get("attributes"))
                break
    block_type = _text(fact.get("blockType"))
    outline_level, has_outline_fact = _outline_fact(fact)
    block_roles = {
        "listItem": ("list_item", {"level": max(1, min(9, _number(fact.get("listLevel"), 1)))}, "block_type"),
        "caption": ("caption", {}, "block_type"),
        "paragraph": ("body", {}, "block_type"),
        "tableCell": ("table_body", {}, "block_type"),
        "formula": ("formula", {}, "block_type"),
    }
    if block_type in block_roles:
        role, attributes, source = block_roles[block_type]
        add(role, source, attributes)
    elif block_type == "heading" and (not has_outline_fact or outline_level in range(1, 10)):
        add("heading", "block_type", {"level": outline_level or 1})

    if fact.get("isHeading") is True:
        if not has_outline_fact or outline_level in range(1, 10):
            add("heading", "structural_field", {"level": outline_level or 1})
    if fact.get("isCaption") is True:
        add("caption", "structural_field")
    if fact.get("isTableCell") is True:
        add("table_body", "structural_field")

    numbering = fact.get("numbering") if isinstance(fact.get("numbering"), dict) else {}
    num_fmt = _normalized(fact.get("numFmt") or numbering.get("numFmt"))
    list_label = _text(fact.get("listLabel") or fact.get("marker"))
    if num_fmt in _ORDERED_FORMATS or num_fmt in {"bullet", "none"} or list_label:
        ordered = num_fmt in _ORDERED_FORMATS or bool(re.match(r"^[（(]?\d+[）)]", list_label))
        add(
            "list_item",
            "numbering" if num_fmt else "visible_list_marker",
            {"level": max(1, min(9, _number(fact.get("level") or numbering.get("level"), 1))), "ordered": ordered},
        )

    text = _text(fact.get("text"))
    if _caption_kind(text) != "unknown":
        add("caption", "visible_caption_marker")
    if re.match(r"^注\s*(?:\d+\s*)?[：:．.]", text):
        add("note", "visible_note_marker", {"numbered": bool(re.match(r"^注\s*\d+", text))})
    if re.match(r"^附\s*录", text, re.IGNORECASE):
        add("appendix_title", "visible_appendix_marker")
    if re.match(r"^[A-Z]((?:\.\d+){1,3})\s+", text, re.IGNORECASE):
        add("appendix_heading", "visible_appendix_heading_marker", {"level": min(3, text.split(" ", 1)[0].count("."))})
    heading_match = re.match(r"^(\d+(?:\.\d+){0,8})(?:\s+|　+)", text)
    has_explicit_body_evidence = block_type in {"paragraph", "tableCell", "formula"} or (
        has_outline_fact and outline_level not in range(1, 10)
    )
    if heading_match and not num_fmt and not has_explicit_body_evidence:
        add("heading", "visible_heading_marker", {"level": min(9, heading_match.group(1).count(".") + 1)})
    if outline_level == 0:
        add("body", "outline_level")
    elif outline_level in range(1, 10):
        add("heading", "outline_level", {"level": outline_level})

    if fact.get("role"):
        legacy = _legacy_role(fact.get("role"))
        if legacy and _text(fact.get("roleSource")) in {"structural", "wps", "adapter"} and (
            legacy["role"] not in {"heading", "appendix_heading"}
            or not has_outline_fact
            or outline_level in range(1, 10)
        ):
            add(legacy["role"], "provided_role", legacy.get("attributes"))

    style_name = _text(fact.get("styleName"))
    all_evidence = [item for values in evidence.values() for item in values]
    if style_name:
        all_evidence.append("style_observed")
    if len(candidates) > 1:
        return {
            "role": "unknown",
            "attributes": {},
            "status": "conflict",
            "evidence": all_evidence,
            "candidates": [
                {"role": role, "attributes": candidates[role], "evidence": evidence[role]}
                for role in sorted(candidates)
            ],
        }
    if not candidates:
        return {"role": "unknown", "attributes": {}, "status": "needs_confirmation", "evidence": all_evidence}

    role = next(iter(candidates))
    role_evidence = evidence[role]
    direct = any(item in role_evidence for item in (
        "structural_role", "block_type", "structural_field", "provided_role", "outline_level"
    ))
    strong = len(set(role_evidence)) >= 2 or ("visible_heading_marker" in role_evidence and "outline_level" in role_evidence)
    status = "confirmed" if direct or strong else "needs_confirmation"
    return {
        "role": role if status == "confirmed" else "unknown",
        "attributes": candidates[role] if status == "confirmed" else {},
        "status": status,
        "evidence": all_evidence,
        "candidate": {"role": role, "attributes": candidates[role]},
    }


def resolve_role_rule(role_result: Any, pack: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve a confirmed semantic role through an explicit template mapping."""
    if isinstance(role_result, str):
        legacy = _legacy_role(role_result)
        role_result = {
            "role": legacy["role"] if legacy else role_result,
            "attributes": legacy.get("attributes", {}) if legacy else {},
            "status": "confirmed",
        }
    role_result = role_result if isinstance(role_result, dict) else {}
    status = role_result.get("status", "needs_confirmation")
    if status != "confirmed":
        return {"status": status, "ruleKey": "", "role": role_result.get("role", "unknown")}
    role = _text(role_result.get("role")) or "unknown"
    attributes = role_result.get("attributes") if isinstance(role_result.get("attributes"), dict) else {}
    template = pack.get("template", {}) if isinstance(pack, dict) else {}
    mappings = template.get("roleMappings") if isinstance(template.get("roleMappings"), dict) else {}
    mapping = mappings.get(role)
    rule_key = None
    if isinstance(mapping, str):
        rule_key = mapping
    elif isinstance(mapping, dict):
        level = str(attributes.get("level", ""))
        if role == "heading" or role == "appendix_heading":
            rule_key = mapping.get(level) or mapping.get("level" + level)
        elif role == "list_item":
            ordered_key = "numbered" if attributes.get("ordered") else "plain"
            candidate = mapping.get(level) or mapping.get("level" + level)
            if isinstance(candidate, dict):
                rule_key = candidate.get(ordered_key)
            elif isinstance(candidate, str):
                rule_key = candidate
        elif role == "note":
            rule_key = mapping.get("numbered" if attributes.get("numbered") else "unumbered")
        else:
            rule_key = mapping.get(level) or mapping.get("default")
    if not isinstance(rule_key, str) or not rule_key:
        return {"status": "unconfigured", "ruleKey": role, "role": role}
    if rule_key not in (template.get("roleRules") or {}):
        return {"status": "unconfigured", "ruleKey": rule_key, "role": role}
    return {"status": "mapped", "ruleKey": rule_key, "role": role}


def heading_hierarchy_warnings(heading_sequence: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return only observed hierarchy violations; never infer missing headings."""
    warnings = []
    seen_violation_targets = set()
    normalized_sequence = []
    for heading in heading_sequence or []:
        if not isinstance(heading, dict):
            continue
        level = normalize_heading_level(heading.get("level"))
        if level is None:
            continue
        normalized_sequence.append({**heading, "level": level})
    if not normalized_sequence:
        return warnings
    previous = normalized_sequence[0]
    previous_level = previous["level"]
    if previous_level > 1:
        target_key = (previous.get("paragraphIndex"), previous_level)
        if target_key not in seen_violation_targets:
            seen_violation_targets.add(target_key)
            warnings.append(
                {
                    "type": "first_heading_below_level_one",
                    "level": previous_level,
                    "text": _text(previous.get("text")),
                    "paragraphIndex": previous.get("paragraphIndex"),
                }
            )
    for heading in normalized_sequence[1:]:
        level = heading["level"]
        if previous_level and level > previous_level + 1:
            target_key = (heading.get("paragraphIndex"), level)
            if target_key not in seen_violation_targets:
                seen_violation_targets.add(target_key)
                warnings.append(
                    {
                        "type": "heading_level_jump",
                        "previousLevel": previous_level,
                        "level": level,
                        "text": _text(heading.get("text")),
                        "paragraphIndex": heading.get("paragraphIndex"),
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
    return {
        "role": "list_item",
        "attributes": {"level": level, "ordered": list_type == "numbered"},
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
    cells = [cell for cell in fact.get("cells", []) if isinstance(cell, dict)]
    if not cells and isinstance(fact.get("rows"), list):
        for row_index, row in enumerate(fact.get("rows", [])):
            if not isinstance(row, dict):
                continue
            for column_index, cell in enumerate(row.get("cells", [])):
                if isinstance(cell, dict):
                    cells.append(
                        {
                            **cell,
                            "row": cell.get("row", cell.get("rowIndex", row.get("rowIndex", row_index))),
                            "column": cell.get("column", cell.get("columnIndex", column_index)),
                        }
                    )
    cells = _unique_cells(cells)
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

    rows: Dict[int, List[Dict[str, Any]]] = {}
    for cell in cells:
        row = _number(cell.get("row", cell.get("rowIndex")), 0)
        rows.setdefault(row, []).append(cell)
    row_values = [row for _, row in sorted(rows.items())]
    header_rows = max(0, _number(fact.get("headerRows"), 0))
    explicit_headers = [cell for cell in cells if cell.get("isHeader") is True or cell.get("header") is True]
    has_header = bool(explicit_headers or header_rows > 0)
    if explicit_headers and not header_rows:
        header_rows = 1
    data_rows = row_values[header_rows:] if header_rows else row_values
    explicit_columns = fact.get("columnSemantics")
    stable_columns = isinstance(explicit_columns, list) and len(
        [item for item in explicit_columns if _text(item)]
    ) >= 2
    repeated_shape = len(data_rows) >= 3 and len(set(len(row) for row in data_rows)) == 1 and len(data_rows[0]) >= 2
    consistent_columns = bool(data_rows) and len(set(len(row) for row in data_rows)) == 1 and len(data_rows[0]) >= 2
    explicit_record_count = max(
        _number(fact.get("recordCount"), 0), _number(fact.get("dataRowCount"), 0)
    )
    multi_row_records = explicit_record_count >= 2 or repeated_shape
    positive_evidence = []
    if has_header:
        positive_evidence.append("header_row")
    if stable_columns:
        positive_evidence.append("stable_column_semantics")
    if repeated_shape:
        positive_evidence.append("repeated_row_structure")
    if explicit_record_count >= 2:
        positive_evidence.append("multi_row_records")
    if (has_header and consistent_columns and data_rows) or stable_columns and data_rows or multi_row_records:
        if not positive_evidence:
            positive_evidence.append("relational_table_shape")
        return {
            "tableType": "data",
            "captionEligible": True,
            "visualCellCount": len(cells),
            "headerRows": header_rows,
            "dataRowCount": len(data_rows) if data_rows else explicit_record_count,
            "evidence": positive_evidence,
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
    """Associate bounded same-story captions and report placement independently."""
    results = []

    def block_id(block: Dict[str, Any], index: int) -> str:
        return _text(block.get("objectId") or block.get("tableId") or block.get("blockId")) or str(index)

    def same_story(left: Dict[str, Any], right: Dict[str, Any], distance: int) -> bool:
        section_left = _text(left.get("sectionId") or left.get("section"))
        section_right = _text(right.get("sectionId") or right.get("section"))
        story_left = _text(left.get("storyId") or left.get("story"))
        story_right = _text(right.get("storyId") or right.get("story"))
        return bool(section_left and story_left and section_left == section_right and story_left == story_right)

    def is_boundary(block: Dict[str, Any]) -> bool:
        return _text(block.get("type") or block.get("blockType")) in {"sectionBreak", "storyBreak"} or bool(block.get("sectionBoundary") or block.get("storyBoundary"))

    def object_type(block: Dict[str, Any]) -> str:
        return _text(block.get("type") or block.get("blockType"))

    def compatible(caption_type: str, candidate: Dict[str, Any]) -> bool:
        candidate_type = object_type(candidate)
        if candidate_type not in _CAPTION_OBJECT_TYPES or caption_type not in {"unknown", candidate_type}:
            return False
        return candidate_type != "table" or bool(candidate.get("captionEligible"))

    def candidates_for(caption_index: int, caption: Dict[str, Any]) -> List[Tuple[int, Dict[str, Any]]]:
        explicit_target = _text(caption.get("captionFor") or caption.get("objectId"))
        caption_type = _caption_kind(_text(caption.get("text")))
        found = []
        for candidate_index, candidate in enumerate(blocks):
            if candidate_index == caption_index or abs(candidate_index - caption_index) > _CAPTION_MAX_DISTANCE:
                continue
            if is_boundary(candidate) or not compatible(caption_type, candidate):
                continue
            if not same_story(caption, candidate, abs(candidate_index - caption_index)):
                continue
            if explicit_target and block_id(candidate, candidate_index) != explicit_target:
                continue
            if any(is_boundary(blocks[pos]) for pos in range(min(candidate_index, caption_index) + 1, max(candidate_index, caption_index))):
                continue
            found.append((candidate_index, candidate))
        return found

    def caption_candidates_for_object(object_index: int, object_block: Dict[str, Any]) -> List[int]:
        found = []
        object_type_name = object_type(object_block)
        for candidate_index, candidate in enumerate(blocks):
            if candidate_index == object_index or object_type(candidate) != "caption":
                continue
            distance = abs(candidate_index - object_index)
            if distance > _CAPTION_MAX_DISTANCE or not same_story(object_block, candidate, distance):
                continue
            if any(is_boundary(blocks[pos]) for pos in range(min(candidate_index, object_index) + 1, max(candidate_index, object_index))):
                continue
            caption_type = _caption_kind(_text(candidate.get("text")))
            if caption_type in {"unknown", object_type_name}:
                found.append(candidate_index)
        return found

    for index, block in enumerate(blocks):
        if object_type(block) != "caption":
            continue
        caption_type = _caption_kind(_text(block.get("text")))
        candidates = candidates_for(index, block)
        if len(candidates) == 1:
            object_index, candidate = candidates[0]
            candidate_type = object_type(candidate)
            adjacent = abs(object_index - index) == 1
            position = "before" if index < object_index else "after"
            expected_position = "before" if candidate_type == "table" else "after"
            results.append(
                {
                    "captionIndex": index,
                    "objectIndex": object_index,
                    "objectId": block_id(candidate, object_index),
                    "status": "associated",
                    "associationStatus": "associated",
                    "captionType": caption_type,
                    "placement": position,
                    "expectedPlacement": expected_position,
                    "placementStatus": "compliant" if adjacent and position == expected_position else ("violation" if adjacent else "non_adjacent"),
                }
            )
        elif len(candidates) > 1:
            results.append(
                {
                    "captionIndex": index,
                    "status": "ambiguous",
                    "associationStatus": "ambiguous",
                    "captionType": caption_type,
                    "candidateObjectIndices": [item[0] for item in candidates],
                }
            )
        else:
            results.append(
                {
                    "captionIndex": index,
                    "status": "orphaned",
                    "associationStatus": "orphaned",
                    "captionType": caption_type,
                }
            )

    associated_by_object: Dict[int, List[Dict[str, Any]]] = {}
    for result in results:
        if result.get("status") == "associated":
            associated_by_object.setdefault(result["objectIndex"], []).append(result)
    duplicate_object_results = []
    for duplicate_results in associated_by_object.values():
        if len(duplicate_results) <= 1:
            continue
        first = duplicate_results[0]
        duplicate_object_results.append(
            {
                "objectIndex": first["objectIndex"],
                "objectId": first.get("objectId"),
                "status": "ambiguous",
                "associationStatus": "ambiguous",
                "captionType": first.get("captionType", "unknown"),
                "captionIndices": [item.get("captionIndex") for item in duplicate_results],
                "ambiguityReason": "multiple_captions_for_object",
            }
        )
    if duplicate_object_results:
        duplicate_indexes = {
            id(result)
            for duplicate_results in associated_by_object.values()
            if len(duplicate_results) > 1
            for result in duplicate_results
        }
        results = [result for result in results if id(result) not in duplicate_indexes]
        results.extend(duplicate_object_results)

    ambiguous_caption_indices = {
        result.get("captionIndex")
        for result in results
        if result.get("status") == "ambiguous" and result.get("captionIndex") is not None
    }
    for object_index, block in enumerate(blocks):
        if object_type(block) not in _CAPTION_OBJECT_TYPES:
            continue
        if object_type(block) == "table" and not block.get("captionEligible"):
            continue
        object_candidates = caption_candidates_for_object(object_index, block)
        existing = [result for result in results if result.get("objectIndex") == object_index]
        if existing:
            continue
        if object_candidates and all(index in ambiguous_caption_indices for index in object_candidates):
            continue
        if object_candidates:
            results.append({
                "objectIndex": object_index,
                "objectId": block_id(block, object_index),
                "status": "ambiguous",
                "associationStatus": "ambiguous",
                "captionType": object_type(block),
                "ambiguityReason": "candidate_caption_not_uniquely_associated",
            })
        else:
            results.append({
                "objectIndex": object_index,
                "objectId": block_id(block, object_index),
                "status": "missing",
                "associationStatus": "missing",
                "captionType": object_type(block),
            })
    return results


def classify_appendix_fact(style_name: Any, text: Any) -> Optional[Dict[str, Any]]:
    result = classify_role_fact({"styleName": style_name, "text": text})
    if result.get("status") == "confirmed":
        return result
    if result.get("candidate"):
        return {
            "role": "unknown",
            "attributes": {},
            "status": result.get("status", "needs_confirmation"),
            "candidate": result["candidate"],
            "evidence": result.get("evidence", []),
        }
    if _text(style_name):
        return {
            "role": "unknown",
            "attributes": {},
            "status": "needs_confirmation",
            "evidence": ["style_observed"],
        }
    return None


def classify_note_fact(style_name: Any, numbering: Optional[Dict[str, Any]], text: Any) -> Optional[Dict[str, Any]]:
    style = _normalized(style_name)
    candidates = []
    if "注-有编号注" in style:
        candidates.append(("style_observed", True))
    elif "注-无编号注" in style:
        candidates.append(("style_observed", False))
    numbering = numbering or {}
    level_text = _normalized(numbering.get("lvlText"))
    num_fmt = _normalized(numbering.get("numFmt"))
    if re.match(r"^注%?\d*[：:]$", level_text):
        candidates.append(("note_numbering", num_fmt in _ORDERED_FORMATS))
    value = _text(text)
    if re.match(r"^注\s*\d+\s*[：:]", value):
        candidates.append(("visible_note_marker", True))
    elif re.match(r"^注\s*[：:]", value):
        candidates.append(("visible_note_marker", False))
    if not candidates:
        return None
    evidence = [item[0] for item in candidates]
    attributes = {item[1] for item in candidates}
    if len(attributes) > 1:
        return {
            "role": "unknown",
            "attributes": {},
            "status": "conflict",
            "candidates": [
                {"role": "note", "attributes": {"numbered": numbered}}
                for numbered in sorted(attributes)
            ],
            "evidence": evidence,
        }
    numbered = next(iter(attributes))
    status = "confirmed" if len(set(evidence)) >= 2 else "needs_confirmation"
    return {
        "role": "note" if status == "confirmed" else "unknown",
        "attributes": {"numbered": numbered} if status == "confirmed" else {},
        "status": status,
        "candidate": {"role": "note", "attributes": {"numbered": numbered}},
        "evidence": evidence,
    }


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
    for paragraph in facts.get("paragraphs", []):
        if not isinstance(paragraph, dict):
            continue
        role_result = classify_role_fact(paragraph)
        if role_result.get("status") != "confirmed":
            continue
        mapping = resolve_role_rule(role_result, pack)
        if mapping.get("status") != "mapped":
            continue
        expected = pack.get("template", {}).get("roleRules", {}).get(mapping["ruleKey"])
        if not isinstance(expected, dict):
            continue
        for field, label in (("fontName", "font_name"), ("fontSize", "font_size")):
            if field not in paragraph or field not in expected:
                continue
            if paragraph.get(field) != expected.get(field):
                issues.append(
                    {
                        "ruleId": label,
                        "role": role_result.get("role", "unknown"),
                        "currentValue": paragraph.get(field),
                        "expectedValue": expected.get(field),
                        "status": "violation",
                    }
                )
    if "heading_hierarchy" in algorithms:
        for warning in heading_hierarchy_warnings(facts.get("headings", [])):
            issues.append({"ruleId": "structure.heading_hierarchy", "status": "violation", **warning})
    roles = [
        classify_role_fact(paragraph)
        for paragraph in facts.get("paragraphs", [])
        if isinstance(paragraph, dict)
    ]
    tables = []
    if "table_semantics" in algorithms:
        tables = [classify_table_fact(table) for table in facts.get("tables", [])]
    captions = []
    if "caption_placement" in algorithms:
        caption_blocks = [
            deepcopy(block)
            for block in facts.get("blocks", [])
            if isinstance(block, dict)
        ]
        table_results_by_id = {}
        unnamed_table_results = []
        for index, table in enumerate(facts.get("tables", [])):
            if index < len(tables) and isinstance(table, dict):
                key = _text(table.get("tableId") or table.get("objectId") or table.get("blockId"))
                if key:
                    table_results_by_id[key] = tables[index]
                else:
                    unnamed_table_results.append(tables[index])
        unnamed_table_index = 0
        for block in caption_blocks:
            key = _text(block.get("tableId") or block.get("objectId") or block.get("blockId"))
            table_result = table_results_by_id.get(key)
            if table_result is None and _text(block.get("type") or block.get("blockType")) == "table":
                if unnamed_table_index < len(unnamed_table_results):
                    table_result = unnamed_table_results[unnamed_table_index]
                    unnamed_table_index += 1
            if table_result is not None:
                block["captionEligible"] = table_result.get("captionEligible", False)
        captions = associate_captions(caption_blocks)
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
            role
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
        "roles": roles,
        "tables": tables,
        "captions": captions,
        "lists": lists,
        "appendixRoles": appendix_roles,
        "noteRoles": note_roles,
    }
