"""Python 3.8-safe adaptation of the authorized WX format algorithms."""

from .algorithm import (
    audit_format_facts,
    classify_appendix_fact,
    classify_list_fact,
    classify_note_fact,
    classify_table_fact,
    heading_hierarchy_warnings,
)

__all__ = [
    "audit_format_facts",
    "classify_appendix_fact",
    "classify_list_fact",
    "classify_note_fact",
    "classify_table_fact",
    "heading_hierarchy_warnings",
]
