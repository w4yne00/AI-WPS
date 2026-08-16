"""Shared, conservative identity data for deterministic format issues."""

import hashlib
import json
import math
from typing import Any, Dict, Optional

from app.services.document_normalizer import body_paragraphs


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

    block_index = -1
    block = None
    for candidate_index, candidate in enumerate(blocks):
        if normalize_paragraph_index(candidate.get("paragraphIndex")) == index:
            block_index = candidate_index
            block = candidate
            break
    if block is None:
        return {"anchorId": "", "sourceAnchor": {}, "anchorVerification": "unverified"}

    block_id = str(block.get("blockId") or "").strip()
    block_text = str(block.get("text") or "")
    if not block_id or not block_text:
        return {"anchorId": "", "sourceAnchor": {}, "anchorVerification": "unverified"}

    adjacent_ids = [
        str(candidate.get("blockId") or "")
        for candidate in blocks[max(0, block_index - 1):block_index + 2]
        if candidate.get("blockId")
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
