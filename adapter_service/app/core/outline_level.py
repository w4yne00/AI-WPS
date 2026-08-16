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
