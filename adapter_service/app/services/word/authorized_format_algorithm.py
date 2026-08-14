"""Application seam for the licensed offline format recognition algorithms."""

from vendor.wx_doc_format_algorithm.algorithm import (
    audit_format_facts,
    associate_captions,
    classify_appendix_fact,
    classify_list_fact,
    classify_note_fact,
    classify_role_fact,
    classify_table_fact,
    heading_hierarchy_warnings,
    resolve_role_rule,
)

__all__ = [
    "audit_format_facts",
    "associate_captions",
    "classify_appendix_fact",
    "classify_list_fact",
    "classify_note_fact",
    "classify_role_fact",
    "classify_table_fact",
    "heading_hierarchy_warnings",
    "resolve_role_rule",
]
