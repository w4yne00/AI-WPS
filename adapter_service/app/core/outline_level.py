"""Canonical WPS Word outline-level normalization."""

import math
from typing import Any, Optional


def normalize_outline_level(value: Any) -> Optional[int]:
    """Return a WPS outline level, or ``None`` when the fact is unknown.

    WPS uses 10 (as well as 0 in some clients) for body text. Only integer
    levels 1 through 9 are heading levels; all other values stay unknown.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric) or not numeric.is_integer():
        return None
    level = int(numeric)
    if level in (0, 10):
        return 0
    if 1 <= level <= 9:
        return level
    return None


def normalize_heading_level(value: Any) -> Optional[int]:
    """Return only the valid heading subset of a WPS outline level."""
    level = normalize_outline_level(value)
    return level if level is not None and level > 0 else None


def normalize_format_block_outline_level(block: Any) -> Optional[int]:
    """Normalize the authoritative outline fact from a format block.

    ``headingLevel`` is a derived convenience field. When a client sends both
    fields, the raw ``outlineLevel`` (including a nested format fact) wins so
    an inconsistent derived heading cannot turn WPS body level ``10`` into a
    heading.
    """
    if not isinstance(block, dict):
        return None
    if "outlineLevel" in block:
        return normalize_outline_level(block.get("outlineLevel"))
    format_facts = block.get("format")
    if isinstance(format_facts, dict) and "outlineLevel" in format_facts:
        return normalize_outline_level(format_facts.get("outlineLevel"))
    if "headingLevel" in block:
        return normalize_outline_level(block.get("headingLevel"))
    return None
