import os


FULL_DOCUMENT_REVIEW_ENV = "AI_WPS_ENABLE_FULL_DOCUMENT_REVIEW"
DETERMINISTIC_FORMAT_REVIEW_ENV = "AI_WPS_ENABLE_DETERMINISTIC_FORMAT_REVIEW"


def full_document_review_enabled() -> bool:
    return os.environ.get(FULL_DOCUMENT_REVIEW_ENV, "").strip() == "1"


def deterministic_format_review_enabled() -> bool:
    return os.environ.get(DETERMINISTIC_FORMAT_REVIEW_ENV, "").strip() == "1"
