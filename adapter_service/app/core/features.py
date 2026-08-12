import os


FULL_DOCUMENT_REVIEW_ENV = "AI_WPS_ENABLE_FULL_DOCUMENT_REVIEW"


def full_document_review_enabled() -> bool:
    return os.environ.get(FULL_DOCUMENT_REVIEW_ENV, "").strip() == "1"
