import re
import unicodedata
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Dict, Iterable, Mapping, Optional, Tuple


KNOWLEDGE_SCOPES = (
    "global",
    "word.smart_write",
    "word.smart_imitation",
    "word.document_review",
)
TASK_SCOPES = KNOWLEDGE_SCOPES[1:]
PRIORITIES = ("high", "medium", "low")

MAX_IMPORT_BYTES = 5 * 1024 * 1024
MAX_IMPORT_ROWS = 5000
MAX_CELL_CHARS = 2000
MAX_XLSX_EXPANDED_BYTES = 20 * 1024 * 1024
MAX_TERM_MATCHES = 30
MAX_STYLE_RULES = 8
MAX_PROMPT_CHARS = 3000
MAX_PUBLIC_MATCHED_ITEMS = 20
PREVIEW_TTL_SECONDS = 600
MAX_DATABASE_BACKUPS = 3

_WHITESPACE_RE = re.compile(r"\s+")


class KnowledgeError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, init=False)
class KnowledgeMatchResult:
    prompt_block: str
    matched_item_ids: Tuple[str, ...]
    _usage: Dict[str, object] = field(repr=False)
    _diagnostic: Dict[str, object] = field(repr=False)

    def __init__(
        self,
        prompt_block: str,
        usage: Dict[str, object],
        matched_item_ids: Tuple[str, ...],
        diagnostic: Optional[Dict[str, object]] = None,
    ):
        object.__setattr__(self, "prompt_block", prompt_block)
        object.__setattr__(self, "matched_item_ids", tuple(matched_item_ids))
        object.__setattr__(self, "_usage", deepcopy(usage))
        object.__setattr__(self, "_diagnostic", deepcopy(diagnostic or {}))

    @property
    def usage(self) -> Dict[str, object]:
        return deepcopy(self._usage)

    @property
    def diagnostic(self) -> Dict[str, object]:
        return deepcopy(self._diagnostic)

    def diagnostic_patch(self) -> Dict[str, object]:
        return deepcopy(self._diagnostic)


def normalize_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return _WHITESPACE_RE.sub(" ", normalized).strip()


def public_usage(
    *,
    applied: bool,
    terms: int,
    styles: int,
    truncated: int,
    matched_items: Iterable[Mapping[str, object]],
    degraded: bool = False,
    degraded_reason: str = "",
) -> Dict[str, object]:
    public_items = []
    for item in matched_items:
        if len(public_items) >= MAX_PUBLIC_MATCHED_ITEMS:
            break
        public_items.append(
            {
                "id": item.get("id"),
                "type": item.get("type"),
                "name": item.get("name"),
            }
        )

    return {
        "applied": applied,
        "degraded": degraded,
        "degradedReason": degraded_reason,
        "termMatchCount": terms,
        "styleRuleCount": styles,
        "truncatedCount": truncated,
        "matchedItems": public_items,
    }
