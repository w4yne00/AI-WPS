"""Shared, conservative identity data for deterministic format issues."""

import hashlib
import json
import math
from typing import Any, Dict, Optional

from app.services.document_normalizer import body_paragraphs


_ANCHOR_PARAGRAPH_BLOCK_TYPES = {
    "paragraph",
    "heading",
    "listItem",
    "caption",
    "formula",
    "tableCell",
}


def apply_format_block_story_identity(block: Dict[str, Any]) -> Dict[str, Any]:
    """Attach section and body-story identity from the extraction contract."""
    if not isinstance(block, dict):
        return block
    range_data = block.get("range") if isinstance(block.get("range"), dict) else {}
    section_id = str(block.get("sectionId") or block.get("section") or "").strip()
    if not section_id:
        section_index = range_data.get("sectionIndex")
        if type(section_index) is int and section_index > 0:
            section_id = "section-{0}".format(section_index)
    story_id = str(block.get("storyId") or block.get("story") or "").strip()
    if not story_id and str(block.get("scope") or "in_scope") != "context":
        story_id = "body"
    if section_id:
        block["sectionId"] = section_id
    if story_id:
        block["storyId"] = story_id
    return block


def normalize_paragraph_index(value: Any) -> Optional[int]:
    """Return a positive paragraph index, or ``None`` when it is not verified."""
    if value is None or isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric) or not numeric.is_integer():
        return None
    index = int(numeric)
    return index if index > 0 else None


def build_format_issue_anchor(request: Any, paragraph_index: Any) -> Dict[str, Any]:
    """Build the same stable body anchor for sync and background format reviews."""
    index = normalize_paragraph_index(paragraph_index)
    if index is None:
        return {"anchorId": "", "sourceAnchor": {}, "anchorVerification": "unverified"}

    structure = getattr(getattr(request, "content", None), "document_structure", None) or {}
    supplied_blocks = structure.get("formatBlocks") if isinstance(structure, dict) else None
    blocks = [block for block in supplied_blocks or [] if isinstance(block, dict)]
    if not blocks:
        blocks = [
            {
                "blockId": "paragraph-{0}".format(paragraph.index),
                "paragraphIndex": paragraph.index,
                "text": paragraph.text,
                "range": {"paragraphIndex": paragraph.index},
            }
            for paragraph in body_paragraphs(request)
        ]

    anchor_blocks = []
    for candidate in blocks:
        candidate_index = normalize_paragraph_index(candidate.get("paragraphIndex"))
        block_type = str(candidate.get("blockType") or "")
        if candidate_index is None or not str(candidate.get("text") or ""):
            continue
        if block_type and block_type not in _ANCHOR_PARAGRAPH_BLOCK_TYPES:
            continue
        anchor_blocks.append((candidate_index, candidate))
    anchor_blocks.sort(key=lambda item: item[0])

    matching_blocks = [
        (candidate_position, candidate)
        for candidate_position, (candidate_index, candidate) in enumerate(anchor_blocks)
        if candidate_index == index
    ]
    if len(matching_blocks) != 1:
        return {"anchorId": "", "sourceAnchor": {}, "anchorVerification": "unverified"}
    block_position, block = matching_blocks[0]

    block_id = str(block.get("blockId") or "").strip()
    block_text = str(block.get("text") or "")
    if not block_id or not block_text:
        return {"anchorId": "", "sourceAnchor": {}, "anchorVerification": "unverified"}

    adjacent_ids = [
        "format-paragraph-{0}".format(candidate_index)
        for candidate_index, candidate in anchor_blocks[
            max(0, block_position - 1):block_position + 2
        ]
    ]
    adjacent_hash = hashlib.sha256(
        json.dumps(adjacent_ids, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    source_anchor = {
        "anchorId": block_id,
        "blockId": block_id,
        "location": "table" if block.get("blockType") == "table" else "body",
        "paragraphIndex": index,
        "range": dict(block.get("range") or {}),
        "textSha256": hashlib.sha256(block_text.encode("utf-8")).hexdigest(),
        "text": block_text[:240],
        "adjacentBlockIds": adjacent_ids,
        "adjacentStructureSha256": adjacent_hash,
        "verification": "verified",
    }
    return {
        "anchorId": block_id,
        "sourceAnchor": source_anchor,
        "anchorVerification": "verified",
    }
