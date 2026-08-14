import os


FULL_DOCUMENT_REVIEW_ENV = "AI_WPS_ENABLE_FULL_DOCUMENT_REVIEW"
DETERMINISTIC_FORMAT_REVIEW_ENV = "AI_WPS_ENABLE_DETERMINISTIC_FORMAT_REVIEW"


def full_document_review_enabled() -> bool:
    return os.environ.get(FULL_DOCUMENT_REVIEW_ENV, "").strip() == "1"


def deterministic_format_review_enabled() -> bool:
    return os.environ.get(DETERMINISTIC_FORMAT_REVIEW_ENV, "").strip() == "1"


def image_semantics_enabled() -> bool:
    """Read the persisted image switch; missing or malformed data is closed."""
    from app.core.config import default_config_path
    from app.services.word.image_semantics import ImageSemanticConfigStore

    settings = ImageSemanticConfigStore(default_config_path()).get()
    return bool(settings.get("enabled") and settings.get("wpsAcceptanceConfirmed"))
