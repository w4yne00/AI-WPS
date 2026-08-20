"""Source-aware normalization for Word format facts.

The WPS object model exposes a mixture of enums, points, twips and mode
dependent values.  This module keeps the raw observation and makes the unit
conversion explicit at the adapter boundary.  Callers must not infer a unit
from the magnitude of a number.
"""

import math
from copy import deepcopy
from typing import Any, Dict, Optional, Tuple


FACT_SCHEMA_VERSION = "format_snapshot.v2"
FACT_STATUSES = {
    "verified",
    "mixed",
    "unknown",
    "read_failed",
    "unsupported",
    "context_only",
    "insufficient",
}
LENGTH_UNITS = {"pt", "twip", "twips", "mm", "centimeter", "cm"}
LINE_SPACING_MODES = {
    "single",
    "one_point_five",
    "double",
    "multiple",
    "fixed",
    "minimum",
    "unknown",
}


def _status(value: Any, default: str = "verified") -> str:
    candidate = str(value or default)
    return candidate if candidate in FACT_STATUSES else "unknown"


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result and abs(result) != float("inf") else None


def _round_number(value: float) -> float:
    rounded = math.floor(value * 10000.0 + 0.5) / 10000.0
    return int(rounded) if rounded == int(rounded) else rounded


def _round_integer(value: float) -> int:
    return int(math.floor(value + 0.5))


def _value_type(value: Any, fallback: str = "unknown") -> str:
    if isinstance(value, bool):
        return "boolean"
    if _number(value) is not None:
        return "number"
    if isinstance(value, str):
        return "string"
    return fallback


def _fact(
    source: str,
    raw_value: Any,
    raw_unit: str,
    normalized_value: Any,
    normalized_unit: str,
    value_type: str,
    data_status: str = "verified",
    **extra: Any,
) -> Dict[str, Any]:
    result = {
        "source": str(source or "unknown"),
        "rawValue": deepcopy(raw_value),
        "rawUnit": str(raw_unit or "unknown"),
        "normalizedValue": deepcopy(normalized_value),
        "normalizedUnit": str(normalized_unit or "unknown"),
        "valueType": str(value_type or "unknown"),
        "dataStatus": _status(data_status),
    }
    for key, value in extra.items():
        if value is not None:
            result[key] = deepcopy(value)
    return result


def _payload_parts(value: Any, default_unit: str) -> Tuple[Any, str, str, str]:
    if isinstance(value, dict) and (
        "rawValue" in value
        or "normalizedValue" in value
        or "dataStatus" in value
        or "value" in value
        or "rawUnit" in value
    ):
        raw_value = value.get("rawValue", value.get("value"))
        raw_unit = str(value.get("rawUnit") or default_unit or "unknown")
        status = _status(value.get("dataStatus"))
        value_type = str(value.get("valueType") or _value_type(raw_value))
        return raw_value, raw_unit, status, value_type
    return value, default_unit or "unknown", "verified", _value_type(value)


def normalize_numeric_fact(
    value: Any,
    source: str,
    raw_unit: str,
    normalized_unit: str,
    *,
    data_status: Optional[str] = None,
) -> Dict[str, Any]:
    raw_value, unit, payload_status, value_type = _payload_parts(value, raw_unit)
    status = _status(data_status or payload_status)
    numeric = _number(raw_value)
    if status != "verified" or numeric is None:
        return _fact(source, raw_value, unit, None, "unknown", value_type, status)

    unit_key = unit.lower()
    if unit_key not in LENGTH_UNITS and unit_key != normalized_unit.lower():
        return _fact(source, raw_value, unit, None, "unknown", value_type, "unknown")

    if normalized_unit == "pt":
        if unit_key == "pt":
            normalized = _round_number(numeric)
        elif unit_key in {"twip", "twips"}:
            normalized = _round_number(numeric / 20.0)
        elif unit_key in {"mm", "centimeter", "cm"}:
            normalized = _round_number(numeric * (72.0 / 25.4 if unit_key == "mm" else 72.0 / 2.54))
        else:
            return _fact(source, raw_value, unit, None, "unknown", value_type, "unknown")
    elif normalized_unit == "twip":
        if unit_key == "pt":
            normalized = _round_integer(numeric * 20.0)
        elif unit_key in {"twip", "twips"}:
            normalized = _round_integer(numeric)
        elif unit_key in {"mm", "centimeter", "cm"}:
            normalized = _round_integer(numeric * (56.6929133858 if unit_key == "mm" else 566.929133858))
        else:
            return _fact(source, raw_value, unit, None, "unknown", value_type, "unknown")
    else:
        if unit_key != normalized_unit.lower():
            return _fact(source, raw_value, unit, None, "unknown", value_type, "unknown")
        normalized = _round_number(numeric)
    return _fact(source, raw_value, unit, normalized, normalized_unit, "number", status)


def normalize_paper_size_fact(value: Any, source: str = "wps.word.page_setup.paper_size") -> Dict[str, Any]:
    raw_value, unit, payload_status, value_type = _payload_parts(value, "enum")
    status = payload_status
    if status != "verified":
        return _fact(source, raw_value, unit, None, "unknown", value_type, status)
    mapping = {
        7: "A4",
        "7": "A4",
        "a4": "A4",
        "wdpapersizea4": "A4",
        "paper_a4": "A4",
    }
    try:
        normalized = mapping.get(raw_value)
    except TypeError:
        normalized = None
    if normalized is None:
        normalized = mapping.get(str(raw_value).strip().lower())
    if normalized is None:
        return _fact(source, raw_value, unit, None, "paper", value_type, "unknown")
    return _fact(source, raw_value, unit, normalized, "paper", "enum", status)


def normalize_line_spacing_mode(value: Any) -> str:
    if value in (0, "0", "single", "wdlinespacesingle"):
        return "single"
    if value in (1, "1", "one_point_five", "1.5", "wdlinespace1pt5"):
        return "one_point_five"
    if value in (2, "2", "double", "wdlinespacedouble"):
        return "double"
    if value in (3, "3", "minimum", "at_least", "wdlinespaceatleast"):
        return "minimum"
    if value in (4, "4", "fixed", "exactly", "wdlinespaceexactly"):
        return "fixed"
    if value in (5, "5", "multiple", "wdlinespacemultiple"):
        return "multiple"
    text = str(value or "").strip().lower().replace("-", "_")
    return text if text in LINE_SPACING_MODES else "unknown"


def normalize_line_spacing_fact(
    value: Any,
    mode: Any,
    source: str = "wps.word.paragraph_format.line_spacing",
) -> Dict[str, Any]:
    raw_value, raw_unit, payload_status, value_type = _payload_parts(value, "pt")
    payload = value if isinstance(value, dict) else {}
    selected_mode = normalize_line_spacing_mode(payload.get("mode", mode))
    status = payload_status
    if status != "verified":
        return _fact(source, raw_value, raw_unit, None, "unknown", value_type, status, mode=selected_mode)

    numeric = _number(raw_value)
    if numeric is None:
        return _fact(source, raw_value, raw_unit, None, "unknown", value_type, "unknown", mode=selected_mode)
    if selected_mode == "unknown":
        return _fact(source, raw_value, raw_unit, None, "unknown", value_type, "unknown", mode=selected_mode)
    if selected_mode == "multiple":
        if raw_unit not in {"multiple", "factor", "倍"}:
            return _fact(source, raw_value, raw_unit, None, "unknown", value_type, "unknown", mode=selected_mode)
        return _fact(
            source, raw_value, raw_unit, _round_number(numeric), "multiple", "number", status, mode=selected_mode
        )
    if selected_mode in {"single", "one_point_five", "double"}:
        multiples = {"single": 1, "one_point_five": 1.5, "double": 2}
        return _fact(
            source, raw_value, raw_unit, multiples[selected_mode], "multiple", "number", status, mode=selected_mode
        )
    if raw_unit.lower() not in {"pt", "twip", "twips"}:
        return _fact(source, raw_value, raw_unit, None, "unknown", value_type, "unknown", mode=selected_mode)
    length = normalize_numeric_fact(
        {"rawValue": raw_value, "rawUnit": raw_unit, "dataStatus": status, "valueType": value_type},
        source,
        raw_unit,
        "twip",
    )
    length["mode"] = selected_mode
    return length


def normalize_page_setup(
    value: Any,
    facts: Any = None,
) -> Tuple[Dict[str, Any], Dict[str, Dict[str, Any]]]:
    raw_setup = value if isinstance(value, dict) else {}
    supplied_facts = facts if isinstance(facts, dict) else {}
    normalized: Dict[str, Any] = {}
    normalized_facts: Dict[str, Dict[str, Any]] = {}
    paper_value = supplied_facts.get("paperSize", raw_setup.get("paperSize"))
    paper_fact = normalize_paper_size_fact(paper_value)
    normalized_facts["paperSize"] = paper_fact
    if paper_fact["dataStatus"] == "verified":
        normalized["paperSize"] = paper_fact["normalizedValue"]
    elif "paperSize" in raw_setup and not isinstance(raw_setup.get("paperSize"), (int, float)):
        normalized["paperSize"] = raw_setup.get("paperSize")

    for key in ("marginTop", "marginBottom", "marginLeft", "marginRight"):
        supplied = supplied_facts.get(key)
        raw = supplied if supplied is not None else raw_setup.get(key)
        # Legacy scalar page setup values remain untouched.  v2 clients send a
        # fact with an explicit unit, which is the only path that converts it.
        if supplied is None and not isinstance(raw, dict):
            if isinstance(raw_setup.get("paperSize"), (int, float)):
                supplied = {"rawValue": raw, "rawUnit": "pt"}
            else:
                if key in raw_setup:
                    normalized[key] = deepcopy(raw_setup[key])
                continue
        fact = normalize_numeric_fact(
            supplied if supplied is not None else raw,
            "wps.word.page_setup." + key,
            "pt",
            "twip",
        )
        normalized_facts[key] = fact
        if fact["dataStatus"] == "verified":
            normalized[key] = fact["normalizedValue"]
    return normalized, normalized_facts


def normalize_format_facts(value: Any) -> Dict[str, Any]:
    """Normalize a block's v2 facts while retaining v1 scalar fields."""
    source = value if isinstance(value, dict) else {}
    normalized = deepcopy(source)
    block_status = _status(source.get("dataStatus"))
    supplied = source.get("facts")
    if not isinstance(supplied, dict):
        supplied = source.get("formatFacts") if isinstance(source.get("formatFacts"), dict) else {}
    facts: Dict[str, Dict[str, Any]] = {}

    if "fontSize" in supplied or "fontSize" in source:
        candidate = supplied.get("fontSize", source.get("fontSize"))
        fact = normalize_numeric_fact(
            candidate,
            "wps.word.font.size",
            "pt",
            "pt",
            data_status=block_status if block_status != "verified" else None,
        )
        facts["fontSize"] = fact
        if fact["dataStatus"] == "verified":
            normalized["fontSize"] = fact["normalizedValue"]
        elif "fontSize" in supplied or "fontSize" in source:
            normalized["fontSize"] = None

    line_candidate = supplied.get("lineSpacing", source.get("lineSpacing"))
    line_mode = supplied.get("lineSpacingMode", source.get("lineSpacingMode"))
    has_line_fact = (
        "lineSpacing" in supplied
        or "lineSpacingMode" in supplied
        or "lineSpacingMode" in source
        or (block_status != "verified" and line_candidate is not None)
        or isinstance(line_candidate, dict)
    )
    if has_line_fact and (line_candidate is not None or line_mode is not None):
        line_input = line_candidate
        if block_status != "verified" and not isinstance(line_input, dict):
            line_input = {
                "rawValue": line_input,
                "rawUnit": "pt",
                "dataStatus": block_status,
            }
        fact = normalize_line_spacing_fact(line_input, line_mode)
        facts["lineSpacing"] = fact
        normalized["lineSpacingMode"] = fact.get("mode", normalize_line_spacing_mode(line_mode))
        if fact["dataStatus"] == "verified":
            normalized["lineSpacing"] = fact["normalizedValue"]
        elif "lineSpacing" in supplied or "lineSpacing" in source:
            normalized["lineSpacing"] = None

    for key in ("firstLineIndent", "spaceBefore", "spaceAfter", "leftIndent", "rightIndent"):
        if key not in supplied and key not in source:
            continue
        candidate = supplied.get(key, source.get(key))
        fact = normalize_numeric_fact(
            candidate,
            "wps.word.paragraph_format." + key,
            "pt",
            "twip",
            data_status=block_status if block_status != "verified" else None,
        )
        facts[key] = fact
        if fact["dataStatus"] == "verified":
            normalized[key] = fact["normalizedValue"]
        elif key in supplied or key in source:
            normalized[key] = None

    if facts:
        normalized["facts"] = facts
    return normalized
